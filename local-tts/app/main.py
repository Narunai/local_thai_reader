import hmac
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

from .backends import voices
from .bgm import ensure_bgm_tracks, get_bgm_path
from .engine import Engine
from .settings import prepare
from .pronunciation import GeminiOptions, GeminiKeys, GeminiPronouncer, GeminiError, KeyRequest, replace_readings


class JobRequest(BaseModel):
    paragraphs: list[str] = Field(min_length=1, max_length=5000)
    voice: str = "vachana:th_f_1"
    start_paragraph: int = Field(default=0, ge=0)
    dictionary: dict[str, str] = Field(default_factory=dict, max_length=500)
    gemini: GeminiOptions = Field(default_factory=GeminiOptions)

    @model_validator(mode="after")
    def valid_text(self):
        if sum(map(len, self.paragraphs)) > 200_000 or self.start_paragraph >= len(self.paragraphs):
            raise ValueError("ข้อความยาวเกินไปหรือตำแหน่งเริ่มต้นไม่ถูกต้อง")
        if any(len(k) > 200 or len(v) > 500 for k, v in self.dictionary.items()):
            raise ValueError("คำในพจนานุกรมยาวเกินไป")
        if not any(p.strip() for p in self.paragraphs[self.start_paragraph:]):
            raise ValueError("ข้อความว่าง")
        return self


class Cursor(BaseModel):
    index: int = Field(ge=0)


def create_app(engine=None, token=None, catalog=voices, gemini_keys=None, pronouncer_factory=GeminiPronouncer):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine or Engine()
        yield
        if engine is None:
            app.state.engine.close()

    app = FastAPI(title="Novel Local TTS", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    secret = token or prepare()
    keys = gemini_keys or GeminiKeys()

    @app.exception_handler(GeminiError)
    async def gemini_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo validation inputs: these may contain a supplied API key.
        return JSONResponse({"detail": "ข้อมูลไม่ถูกต้อง · ตรวจข้อความ ชื่อโมเดล และการตั้งค่า"}, status_code=422)

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin", "")
        # Reject page origins (including localhost pages); allow extension contexts
        # with the locally paired secret, plus CLI requests with no Origin.
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "Invalid host"}, status_code=403)
        if origin and not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            return JSONResponse({"detail": "Origin denied"}, status_code=403)
        if request.method == "OPTIONS":
            return JSONResponse({}, headers={"Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "Authorization, Content-Type", "Access-Control-Allow-Methods": "GET, POST, DELETE"})
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {secret}"):
            return JSONResponse({"detail": "Token ไม่ถูกต้อง"}, status_code=401)
        if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", 0)) > 2_000_000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    def get_engine():
        return app.state.engine

    def get_job(key):
        try:
            return get_engine().get(key)
        except KeyError:
            raise HTTPException(404, "ไม่พบงาน อาจมีการเริ่มเซิร์ฟเวอร์ใหม่")

    @app.get("/health")
    def health():
        engine = get_engine()
        backend = engine.backend
        with engine.cv:
            cloud = any(job.pronouncer and job.state not in ("cancelled", "error", "complete") for job in engine.jobs.values())
        return {"status": "ok", "model": backend.current or None, "device": backend.device,
                "offline": not cloud, "audio_local": True, "optional_cloud_pronunciation": True}

    @app.get("/gemini")
    def gemini_status():
        return keys.status()

    @app.post("/gemini")
    def gemini_save(body: KeyRequest):
        return keys.save(body.api_key.get_secret_value())

    @app.delete("/gemini")
    def gemini_delete():
        return keys.delete()

    @app.post("/gemini/test")
    def gemini_test(body: GeminiOptions):
        text = "ลอเอลได้รับไอเทม Legendary จำนวน 12 ชิ้น"
        hints = pronouncer_factory(keys.key(), body.model).readings(text, text, use_cache=False)
        return {"ok": True, "model": body.model, "text": text, "speech": replace_readings(text, hints, {})}

    @app.get("/voices")
    def get_voices():
        return catalog()

    @app.get("/bgm")
    def get_bgm_catalog():
        return ensure_bgm_tracks()

    @app.get("/bgm/{track_id}")
    def get_bgm_audio(track_id: str):
        path = get_bgm_path(track_id)
        if not path:
            raise HTTPException(404, "ไม่พบไฟล์เพลงคลอพื้นหลัง")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "max-age=3600"})

    @app.post("/jobs", status_code=201)
    def create_job(body: JobRequest):
        if not any(v["id"] == body.voice and v["ready"] for v in catalog()):
            raise HTTPException(409, "เสียงนี้ยังไม่พร้อมใช้งาน กรุณาติดตั้งโมเดลหรือเลือก Vachana")
        pronouncer = pronouncer_factory(keys.key(), body.gemini.model) if body.gemini.enabled else None
        job = get_engine().create(body.paragraphs, body.voice, body.start_paragraph, body.dictionary,
                                  pronouncer=pronouncer, pronunciation_batches=body.gemini.batches)
        return get_engine().snapshot(job.id)

    @app.get("/jobs/{key}")
    def job_status(key: str):
        get_job(key)
        return get_engine().snapshot(key)

    @app.post("/jobs/{key}/cursor")
    def update_cursor(key: str, body: Cursor):
        get_job(key)
        try:
            get_engine().cursor(key, body.index)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {"ok": True}

    @app.get("/jobs/{key}/chunks/{index}")
    def audio(key: str, index: int):
        job = get_job(key)
        if job.state == "cancelled":
            raise HTTPException(410, "ยกเลิกงานแล้ว")
        if not 0 <= index < len(job.chunks):
            raise HTTPException(404, "ไม่พบช่วงเสียง")
        chunk = job.chunks[index]
        if not chunk.path or not chunk.path.exists():
            raise HTTPException(409, "เสียงยังไม่พร้อม")
        return FileResponse(chunk.path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.delete("/jobs/{key}")
    def cancel_job(key: str):
        get_job(key)
        get_engine().cancel(key)
        return {"ok": True}

    return app


app = create_app()
