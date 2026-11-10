import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import soundfile as sf
import numpy as np

from .backends import Backend
from .bgm import BgmCue, analyze_segments_bgm, apply_scene_cues
from .settings import CACHE_DIR
from .text import Segment, segment_paragraphs, split_exact
from .pronunciation import GeminiPronouncer, GeminiError, PronunciationBatch, page_batches, replace_readings

log = logging.getLogger(__name__)


@dataclass
class Chunk:
    segment: Segment
    path: Path | None = None
    seconds: float = 0
    pronunciation_batch: int = 0
    bgm: BgmCue = field(default_factory=BgmCue)


@dataclass
class Job:
    id: str
    voice: str
    chunks: list[Chunk]
    cursor: int = 0
    state: str = "queued"
    error: str | None = None
    created: float = field(default_factory=time.monotonic)
    pronouncer: GeminiPronouncer | None = field(default=None, repr=False)
    paragraphs: list[str] = field(default_factory=list, repr=False)
    dictionary: dict[str, str] = field(default_factory=dict, repr=False)
    batches: list[PronunciationBatch] = field(default_factory=list, repr=False)


class Engine:
    def __init__(self, backend=None, cache_dir=CACHE_DIR, cache_limit=2 * 1024**3):
        self.backend = backend or Backend()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_limit = cache_limit
        self.jobs: dict[str, Job] = {}
        self.inflight: set[Path] = set()
        self.cv = threading.Condition(threading.RLock())
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="tts-single-worker", daemon=True)
        self.thread.start()

    def create(self, paragraphs: list[str], voice: str, start: int, dictionary: dict[str, str], pronouncer=None, pronunciation_batches=4) -> Job:
        segments = segment_paragraphs(paragraphs, start, dictionary)
        if not segments:
            raise ValueError("ไม่พบข้อความที่จะอ่าน")
        with self.cv:
            # The app has one reading session. Cancel even an in-flight old job.
            for old in self.jobs.values():
                if old.state not in ("cancelled", "error"):
                    old.state = "cancelled"
            self.jobs = {key: value for key, value in self.jobs.items() if time.monotonic() - value.created < 3600}
            if len(self.jobs) >= 20:
                del self.jobs[next(iter(self.jobs))]
            batches = page_batches(segments, pronunciation_batches) if pronouncer else []
            cues = analyze_segments_bgm(segments, paragraphs)
            chunks = [Chunk(s, bgm=cues[i]) for i, s in enumerate(segments)]
            for index, batch in enumerate(batches):
                for chunk in chunks[batch.start:batch.end]:
                    chunk.pronunciation_batch = index
            job = Job(uuid.uuid4().hex, voice, chunks,
                      pronouncer=pronouncer, paragraphs=list(paragraphs), dictionary=dict(dictionary), batches=batches)
            self.jobs[job.id] = job
            self.cv.notify_all()
            return job

    def get(self, key: str) -> Job:
        with self.cv:
            return self.jobs[key]

    def cancel(self, key: str):
        with self.cv:
            self.jobs[key].state = "cancelled"
            self.cv.notify_all()
        self.prune()

    def cursor(self, key: str, index: int):
        with self.cv:
            job = self.jobs[key]
            if not 0 <= index < len(job.chunks):
                raise ValueError("ตำแหน่งไม่ถูกต้อง")
            job.cursor = index
            self.cv.notify_all()

    def snapshot(self, key: str) -> dict:
        with self.cv:
            job = self.jobs[key]
            return {"id": job.id, "voice": job.voice, "state": job.state, "error": job.error,
                    "pronunciation": {"total_batches": len(job.batches), "ready_batches": sum(b.readings is not None for b in job.batches)},
                    "chunks": [{"index": i, "paragraph": c.segment.paragraph, "text": c.segment.text,
                                "ready": bool(c.path), "seconds": c.seconds, "bgm": c.bgm.to_dict()} for i, c in enumerate(job.chunks)]}

    def _synthesize(self, job: Job, chunk: Chunk) -> Path:
        speech = chunk.segment.speech
        if job.pronouncer:
            batch = job.batches[chunk.pronunciation_batch]
            if job.state == "cancelled":
                raise GeminiError("ยกเลิกงานแล้ว")
            if batch.readings is None:
                # First API call includes chapter paragraph outline so Gemini interprets
                # scene moods & BGM tempo across the chapter right on the first request.
                context = ""
                if chunk.pronunciation_batch == 0 and job.paragraphs:
                    context = "\n".join(f"[P{i}] {p[:100]}" for i, p in enumerate(job.paragraphs[:80]))
                readings = job.pronouncer.readings(batch.text, context)
                scenes = getattr(job.pronouncer, "last_scenes", None) or []
                if job.state == "cancelled":
                    raise GeminiError("ยกเลิกงานแล้ว")
                with self.cv:
                    batch.readings = readings
                    batch.scenes = scenes
                    if scenes:
                        target_chunks = job.chunks if chunk.pronunciation_batch == 0 else job.chunks[batch.start:batch.end]
                        apply_scene_cues(target_chunks, scenes)
            speech = replace_readings(chunk.segment.text, batch.readings, job.dictionary)
            if job.state == "cancelled":
                raise GeminiError("ยกเลิกงานแล้ว")
        if self.backend.current and self.backend.current != job.voice:
            self.backend.unload()
        key = hashlib.sha256(json.dumps([self.backend.fingerprint(job.voice), speech], ensure_ascii=False).encode()).hexdigest()
        output = self.cache_dir / f"{key}.wav"
        with self.cv:
            self.inflight.add(output)
        try:
            return self._render_cached(job, speech, output)
        finally:
            with self.cv:
                self.inflight.discard(output)

    def _render_cached(self, job: Job, speech: str, output: Path) -> Path:
        if output.exists():
            os.utime(output, None)
            return output
        temp = self.cache_dir / f"{output.stem}.{uuid.uuid4().hex}.tmp.wav"
        try:
            try:
                self.backend.synthesize(job.voice, speech, temp)
            except Exception as exc:
                if not any(word in str(exc).lower() for word in ("out of memory", "cuda error: memory")):
                    raise
                # One OOM retry using shorter input, preserving a single chunk.
                self.backend.unload()
                parts = split_exact(speech, max(20, len(speech) // 2))
                audio, sample_rate = [], None
                for part in parts:
                    self.backend.synthesize(job.voice, part, temp)
                    samples, rate = sf.read(temp, always_2d=True)
                    if sample_rate is not None and sample_rate != rate:
                        raise RuntimeError("อัตราสุ่มเสียงไม่ตรงกัน")
                    audio.append(samples)
                    sample_rate = rate
                sf.write(temp, np.concatenate(audio), sample_rate, subtype="PCM_16")
            info = sf.info(temp)
            if info.frames <= 0:
                raise RuntimeError("โมเดลสร้างเสียงว่าง")
            temp.replace(output)
            return output
        finally:
            temp.unlink(missing_ok=True)

    def prune(self):
        with self.cv:
            pinned = {c.path for j in self.jobs.values() if j.state not in ("cancelled", "error") for c in j.chunks if c.path}
            pinned.update(self.inflight)
            files = sorted((p for p in self.cache_dir.glob("*.wav") if not p.name.endswith('.tmp.wav')), key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in files)
            for path in files:
                if total <= self.cache_limit:
                    break
                if path not in pinned:
                    total -= path.stat().st_size
                    path.unlink(missing_ok=True)

    def _run(self):
        while True:
            with self.cv:
                task = None
                while not self.closed and task is None:
                    for job in self.jobs.values():
                        if job.state in ("cancelled", "error", "complete"):
                            continue
                        for chunk in job.chunks[job.cursor:job.cursor + 3]:
                            if chunk.path is None:
                                task = (job, chunk)
                                break
                        if task:
                            break
                    if task is None:
                        self.cv.wait(timeout=30)
                if self.closed:
                    self.backend.unload()
                    return
                job, chunk = task
                job.state = "running"
            try:
                output = self._synthesize(job, chunk)
                with self.cv:
                    if job.state != "cancelled":
                        chunk.path = output
                        chunk.seconds = sf.info(output).duration
                        if all(c.path for c in job.chunks):
                            job.state = "complete"
                self.prune()
            except Exception as exc:
                # Cloud errors are sanitized: never log request headers or API keys.
                if not isinstance(exc, GeminiError):
                    log.exception("TTS job failed")
                with self.cv:
                    if job.state != "cancelled":
                        job.state = "error"
                        job.error = str(exc) if isinstance(exc, GeminiError) else f"สร้างเสียงไม่สำเร็จ: {exc}. ลองเลือกเสียง Vachana แล้วเริ่มใหม่"

    def close(self):
        with self.cv:
            self.closed = True
            for job in self.jobs.values():
                if job.state not in ("complete", "error"):
                    job.state = "cancelled"
            self.cv.notify_all()
        interrupt = getattr(self.backend, "interrupt", None)
        if interrupt:
            interrupt()
        self.thread.join(timeout=5)
