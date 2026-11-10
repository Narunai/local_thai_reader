import threading
import time

import numpy as np
import soundfile as sf
import pytest
from fastapi.testclient import TestClient

from app.engine import Engine
from app.main import create_app
from app.text import (
    split_exact,
    segment_paragraphs,
    int_to_thai,
    normalize_thai_numbers,
    parse_prosodic_clauses,
    apply_clause_prosody,
    ProsodicClause,
)


class FakeBackend:
    current = ""
    device = "cpu"
    calls = 0
    block = None
    fail_oom = 0

    def fingerprint(self, voice):
        return voice

    def unload(self):
        pass

    def synthesize(self, voice, text, output):
        self.calls += 1
        if self.block:
            self.block.wait(timeout=3)
        if self.fail_oom:
            self.fail_oom -= 1
            raise RuntimeError("CUDA out of memory")
        sf.write(output, np.sin(np.arange(2400) * .1), 24000)


def wait_for(predicate):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Worker did not reach expected state")


@pytest.fixture
def engine(tmp_path):
    value = Engine(FakeBackend(), tmp_path)
    yield value
    value.close()


@pytest.mark.parametrize("text", ["กริดกล่าวว่า “ข้าจะกลับมา!”  ลอเอลยิ้ม\nอีกครั้ง" * 25, "ก" + "้" * 5 + "ทดสอบ" * 60, "A" * 700, " ๑๒๓ 1,221 ภาษาไทย English\t\n" * 25])
def test_lossless_split(text):
    parts = split_exact(text)
    assert "".join(parts) == text
    assert all(parts)
    assert all(len(p) <= 185 for p in parts)


def test_dictionary_preserves_display():
    chunks = segment_paragraphs(["กริดพบลอเอล", "ราคา 1,221 บาท"], 0, {"ลอเอล": "ลอ เอล"})
    assert chunks[0].text == "กริดพบลอเอล"
    assert chunks[0].speech == "กริดพบลอ เอล"
    assert chunks[1].paragraph == 1


@pytest.mark.parametrize("raw,expected", [
    ("111", "หนึ่งร้อยสิบเอ็ด"),
    ("100000", "หนึ่งแสน"),
    ("100,000", "หนึ่งแสน"),
    ("1,221", "หนึ่งพันสองร้อยยี่สิบเอ็ด"),
    ("12,500", "หนึ่งหมื่นสองพันห้าร้อย"),
    ("21", "ยี่สิบเอ็ด"),
    ("11", "สิบเอ็ด"),
    ("101", "หนึ่งร้อยเอ็ด"),
    ("1,000,000", "หนึ่งล้าน"),
    ("ลดราคา 99%", "ลดราคา เก้าสิบเก้าเปอร์เซ็นต์"),
    ("Ch.1 — ตอนที่ 1", "ตอนที่ หนึ่ง — ตอนที่ หนึ่ง"),
    ("[18+]เพื่อนสมัยเด็ก", "[ สิบแปด บวก]เพื่อนสมัยเด็ก"),
    ("เวลา 08.30 น.", "เวลา แปดนาฬิกาสามสิบนาที"),
    ("ตอนที่ 0.2", "ตอนที่ ศูนย์จุดสอง"),
    ("ฤดูร้อนตอนม.2 และขึ้นม.ปลาย", "ฤดูร้อนตอนมอ สอง และขึ้นมอปลาย"),
    ("รออีก 2-3 วัน ในปี พ.ศ. 2569", "รออีก สอง ถึง สาม วัน ในปี พุทธศักราช สองพันห้าร้อยหกสิบเก้า"),
    ("ผู้หญิงแบบสดๆ อยู่ข้างๆ นี่เอง", "ผู้หญิงแบบสด สด อยู่ข้าง ข้าง นี่เอง"),
    ("อ๊ะ! เดี๋ยวสิ เอ๊ะ? อื้อออ~", "อ๊ะ, เดี๋ยวสิ เอ๊ะ, อื้อ,"),
    ("เอ่อ... ต่อให้เป็นเพื่อนสมัยเด็ก", "เอ่อ... ต่อให้เป็นเพื่อนสมัยเด็ก"),
])
def test_normalize_thai_numbers(raw, expected):
    assert normalize_thai_numbers(raw) == expected


def test_parse_prosodic_clauses_and_audio_fx():
    c1 = parse_prosodic_clauses("“...ต่อให้เป็นเพื่อนสมัย”")
    assert len(c1) == 1
    assert c1[0].text == "ต่อให้เป็นเพื่อนสมัย"
    assert c1[0].leading_kind == "ellipsis"
    assert c1[0].leading_pause == pytest.approx(0.55)

    c2 = parse_prosodic_clauses("หลังเลิกเรียน—")
    assert len(c2) == 1
    assert c2[0].text == "หลังเลิกเรียน"
    assert c2[0].ending == "dash"
    assert c2[0].trailing_pause == pytest.approx(0.60)

    c3 = parse_prosodic_clauses("“เอ่อ... คือว่าฉันไม่ได้ตั้งใจ...”")
    assert len(c3) == 2
    assert c3[0].text == "เอ่อ"
    assert c3[0].ending == "ellipsis"
    assert c3[1].text == "คือว่าฉันไม่ได้ตั้งใจ"
    assert c3[1].ending == "ellipsis"

    sr = 24000
    t = np.linspace(0, 1.0, sr, dtype=np.float32)
    synth_voice = 0.5 * np.sin(2 * np.pi * 220 * t).astype(np.float32)

    normal_out = apply_clause_prosody(synth_voice, sr, ProsodicClause(text="ปกติ", ending="normal", trailing_pause=0.28))
    ellipsis_out = apply_clause_prosody(synth_voice, sr, ProsodicClause(text="ลากเสียง", leading_pause=0.55, leading_kind="ellipsis", ending="ellipsis", trailing_pause=0.65))
    dash_out = apply_clause_prosody(synth_voice, sr, ProsodicClause(text="ขีดยาว", ending="dash", trailing_pause=0.60))

    # Ellipsis stretches the word + adds leading & trailing wait pauses
    assert len(ellipsis_out) > len(normal_out) + int(sr * 0.95)
    # Leading 0.55s wait is silence
    assert np.max(np.abs(ellipsis_out[:int(sr * 0.50)])) == 0.0
    # Trailing 0.65s wait is silence
    assert np.max(np.abs(ellipsis_out[-int(sr * 0.60):])) == 0.0
    # Word before "..." fades out smoothly (second half of stretched tail has lower RMS than head)
    voiced_end = len(ellipsis_out) - int(sr * 0.65)
    head_rms = float(np.sqrt(np.mean(ellipsis_out[int(sr * 0.75):int(sr * 1.15)] ** 2)))
    tail_rms = float(np.sqrt(np.mean(ellipsis_out[voiced_end - int(sr * 0.30):voiced_end] ** 2)))
    assert tail_rms < head_rms * 0.45

    # Dash adds 0.60s trailing pause
    assert np.max(np.abs(dash_out[-int(sr * 0.55):])) == 0.0


def test_prefetch_window_and_cache(engine):
    job = engine.create([f"ข้อความลำดับ {i}" for i in range(8)], "test:voice", 0, {})
    wait_for(lambda: sum(c.path is not None for c in job.chunks) == 3)
    time.sleep(.05)
    assert engine.backend.calls == 3
    engine.cursor(job.id, 3)
    wait_for(lambda: sum(c.path is not None for c in job.chunks) == 6)
    second = engine.create(["ข้อความลำดับ 0"], "test:voice", 0, {})
    wait_for(lambda: second.state == "complete")
    assert job.state == "cancelled"
    assert engine.backend.calls == 6


def test_cancellation_discards_inflight(engine):
    engine.backend.block = threading.Event()
    job = engine.create(["กำลังสร้างเสียง"], "test:voice", 0, {})
    wait_for(lambda: engine.backend.calls == 1)
    engine.cancel(job.id)
    engine.backend.block.set()
    time.sleep(.1)
    assert job.state == "cancelled"
    assert job.chunks[0].path is None


def test_oom_retry_and_error(engine):
    engine.backend.fail_oom = 1
    job = engine.create(["ทดสอบเสียงยาวมากสำหรับแบ่งครึ่ง" * 3], "test:voice", 0, {})
    wait_for(lambda: job.state == "complete")
    assert engine.backend.calls >= 3
    engine.backend.fail_oom = 2
    job = engine.create(["ข้อความไม่ซ้ำ"], "test:voice", 0, {})
    wait_for(lambda: job.state == "error")
    assert "Vachana" in job.error


def test_cache_eviction_preserves_active(engine):
    job = engine.create(["หนึ่ง"], "test:voice", 0, {})
    wait_for(lambda: job.state == "complete")
    path = job.chunks[0].path
    engine.cache_limit = 0
    engine.prune()
    assert path.exists()
    engine.cancel(job.id)
    engine.prune()
    assert not path.exists()


def test_eviction_leaves_inflight_cache_and_temporary_wav(engine):
    active = engine.cache_dir / 'a.wav'
    temporary = engine.cache_dir / 'b.tmp.wav'
    sf.write(active, np.zeros(100), 24000)
    sf.write(temporary, np.zeros(100), 24000)
    engine.cache_limit = 0
    engine.inflight.add(active)
    engine.prune()
    assert active.exists() and temporary.exists()
    engine.inflight.clear()
    engine.prune()
    assert not active.exists() and temporary.exists()


def test_api_auth_origins_validation_and_audio(engine):
    app = create_app(engine, "test-secret", catalog=lambda: [{"id": "test:voice", "ready": True}])
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret"}
        assert client.get('/health').status_code == 401
        assert client.get('/health', headers={**headers, "Origin": "https://example.com"}).status_code == 403
        assert client.get('/health', headers={**headers, "Host": "evil.example"}).status_code == 403
        assert client.get('/health', headers={**headers, "Origin": "chrome-extension://" + "a" * 32}).status_code == 200
        assert client.post('/jobs', headers=headers, json={"paragraphs": ["  "]}).status_code == 422
        assert client.post('/jobs', headers=headers, json={"paragraphs": ["ทดสอบ"], "voice": "missing"}).status_code == 409
        response = client.post('/jobs', headers=headers, json={"paragraphs": ["ข้อความเสียง"], "voice": "test:voice"})
        assert response.status_code == 201
        key = response.json()["id"]
        wait_for(lambda: engine.get(key).state == 'complete')
        assert client.get(f'/jobs/{key}/chunks/0', headers=headers).content[:4] == b'RIFF'
        assert client.post(f'/jobs/{key}/cursor', headers=headers, json={"index": 100}).status_code == 422
        assert client.delete(f'/jobs/{key}', headers=headers).status_code == 200
        assert client.get(f'/jobs/{key}/chunks/0', headers=headers).status_code == 410
        assert client.get('/jobs/missing', headers=headers).status_code == 404


def test_installed_vachana_handles_superscript_and_punctuation(tmp_path):
    from app.backends import Backend, voices
    if not any(v['id'] == 'vachana:th_f_1' and v['ready'] for v in voices()):
        pytest.skip('Vachana model not downloaded')
    backend = Backend()
    for index, text in enumerate(['ค่าโจมตีเพิ่มขึ้น ² เท่า และลำดับที่ ①', '…']):
        path = tmp_path / f'{index}.wav'
        backend.synthesize('vachana:th_f_1', text, path)
        assert sf.info(path).duration > 0
    backend.unload()


@pytest.mark.parametrize('voice', ['vachana:th_f_1', 'vachana:th_f_2'])
def test_installed_vachana_empty_cleaned_text_and_reading_continues(tmp_path, voice):
    from app.backends import Backend, voices
    if not any(v['id'] == voice and v['ready'] for v in voices()):
        pytest.skip('Vachana model not downloaded')
    backend = Backend()
    try:
        for index, text in enumerate(['', ' ', '---', '***', '“”', '[ ]', '!!!', 'ๆ', 'ฯ', '🔥', '\u200b', '———']):
            output = tmp_path / f'pause-{index}.wav'
            backend.synthesize(voice, text, output)
            audio, rate = sf.read(output)
            assert rate == backend.model.config.sample_rate
            assert len(audio) / rate == pytest.approx(.2, abs=1/rate)
            assert np.all(audio == 0)
        output = tmp_path / 'speech.wav'
        backend.synthesize(voice, 'ลอเอลกลับมาแล้ว เขาได้รับไอเทม Legendary จำนวน 12 ชิ้น', output)
        audio, rate = sf.read(output)
        assert np.any(audio != 0)
    finally:
        backend.unload()


def test_real_vachana_job_reads_past_separators_without_changing_display(tmp_path):
    from app.backends import Backend, voices
    voice = 'vachana:th_f_1'
    if not any(v['id'] == voice and v['ready'] for v in voices()):
        pytest.skip('Vachana model not downloaded')
    paragraphs = ['---', '***', 'ลอเอลกลับมาแล้ว']
    engine = Engine(Backend(), tmp_path)
    try:
        job = engine.create(paragraphs, voice, 0, {})
        wait_for(lambda: job.state in ('complete','error'))
        assert job.state == 'complete', job.error
        assert [c['text'] for c in engine.snapshot(job.id)['chunks']] == paragraphs
        assert all(c.path and c.path.exists() for c in job.chunks)
    finally:
        engine.close()
        engine.backend.unload()
