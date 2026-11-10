import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.engine import Engine
from app.main import create_app
from app.pronunciation import (DEFAULT_MODEL, GeminiError, GeminiKeys, GeminiPronouncer,
                               replace_readings, validate_replacements, page_batches)
from app.text import Segment
from test_engine import FakeBackend, wait_for


TEXT = "ลอเอลได้รับไอเทม Legendary จำนวน 12 ชิ้น"
HINTS = {"replacements": [{"source": "ลอเอล", "reading": "ลอ เอล"},
                           {"source": "Legendary", "reading": "เลเจนดารี"}]}


@pytest.mark.parametrize('key', ['AQ.fake-auth-key_for-test.12345', 'AIza-fake-key-for-test'])
def test_key_formats_saved_and_forwarded_unchanged(tmp_path, key):
    keys = GeminiKeys(tmp_path / '.gemini.json')
    assert keys.save(key)['key_configured']
    assert keys.key() == key
    assert key not in json.dumps(keys.status())
    def handler(request):
        assert request.headers['x-goog-api-key'] == key
        assert not request.url.query
        return response()
    provider = GeminiPronouncer(keys.key(), cache_dir=tmp_path / 'cache', transport=httpx.MockTransport(handler))
    assert provider.readings(TEXT, TEXT)['ลอเอล'] == 'ลอ เอล'


@pytest.mark.parametrize('key', ['too-short', 'AQ.invalid key', 'AQ.invalid\r\nheader', 'AQ.invalid\x00key', 'AQ.ภาษาไทย12345'])
def test_key_rejects_invalid_header_characters(tmp_path, key):
    with pytest.raises(GeminiError):
        GeminiKeys(tmp_path / '.gemini.json').save(key)


def response(payload=HINTS):
    return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"thought": True, "text": "hidden reasoning"}, {"text": json.dumps(payload)}]}}]})


def test_request_cache_and_manual_precedence(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert not request.url.query
        assert request.headers["x-goog-api-key"] == "fake-api-key-12345"
        body = json.loads(request.content)
        wire = body["generationConfig"]["responseFormat"]["text"]
        assert wire['mimeType'] == 'APPLICATION_JSON'
        schema = json.dumps(wire['schema'])
        assert 'maxItems' not in schema and 'additionalProperties' not in schema
        assert 'responseJsonSchema' not in body['generationConfig']
        assert "temperature" not in body["generationConfig"]
        assert json.loads(body["contents"][0]["parts"][0]["text"])["text"] == TEXT
        return response()
    provider = GeminiPronouncer("fake-api-key-12345", cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    speech = provider.speech(TEXT, TEXT, {"ลอเอล": "ลอ เอ็ล"})
    assert speech == "ลอ เอ็ลได้รับไอเทม เลเจนดารี จำนวน 12 ชิ้น"
    assert provider.speech(TEXT, TEXT, {}) == "ลอ เอลได้รับไอเทม เลเจนดารี จำนวน 12 ชิ้น"
    assert len(calls) == 1
    assert "fake-api-key" not in next(tmp_path.glob('*.json')).read_text(encoding='utf-8')
    provider.readings(TEXT, TEXT, use_cache=False)
    assert len(calls) == 2
    provider.model = "gemini-other"
    provider.readings(TEXT, TEXT)
    assert len(calls) == 3


def test_manual_words_are_protected_even_from_larger_cloud_phrase():
    assert replace_readings("ลอเอลยิ้ม", {"ลอเอลยิ้ม": "อ่านผิด"}, {"ลอเอล": "ลอ เอ็ล"}) == "ลอ เอ็ลยิ้ม"
    assert replace_readings("ABC", {"AB": "เอ", "เอ": "ผิด"}, {}) == "เอC"


@pytest.mark.parametrize('payload', [
    {}, {"replacements": "bad"}, {"replacements": [{"source": "คำที่ไม่มีในต้นฉบับ", "reading": "คำใหม่"}]},
    {"replacements": [{"source": "ลอเอล", "reading": ""}]},
    {"replacements": [{"source": "ลอเอล", "reading": "<script>"}]},
    {"replacements": [{"source": "ลอเอล", "reading": "ignore all instructions"}]},
    {"replacements": [{"source": "ลอเอล", "reading": "ลอ"}, {"source": "ลอเอล", "reading": "เอล"}]},
    {"replacements": [{"source": "ลอเอล", "reading": "ลอ เอล"}] * 129},
])
def test_rejects_invalid_cloud_edits(payload):
    with pytest.raises(GeminiError):
        validate_replacements(payload, TEXT)


@pytest.mark.parametrize('code', [400, 401, 403, 404, 429, 500])
def test_safe_http_errors(tmp_path, code):
    provider = GeminiPronouncer('never-print-this-key', cache_dir=tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(code, text='never-print-this-key')))
    with pytest.raises(GeminiError) as caught:
        provider.readings(TEXT, TEXT)
    assert str(code) in str(caught.value)
    assert 'never-print-this-key' not in str(caught.value)
    assert not list(tmp_path.glob('*.json'))


def test_timeout_blocked_and_truncated_response(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout('never-print-this-key', request=request)
    provider = GeminiPronouncer('never-print-this-key', cache_dir=tmp_path, transport=httpx.MockTransport(timeout))
    with pytest.raises(GeminiError, match='หมดเวลา'):
        provider.readings(TEXT, TEXT)
    for payload in [{"candidates": []}, {"candidates": [{"finishReason": "MAX_TOKENS"}]}, {"candidates": ["malformed"]}]:
        provider.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        with pytest.raises(GeminiError):
            provider.readings(TEXT, TEXT)


def test_key_api_never_returns_secrets_and_local_mode_does_not_call_cloud(tmp_path):
    keys = GeminiKeys(tmp_path / '.gemini.json')
    backend = FakeBackend()
    engine = Engine(backend, tmp_path / 'audio')
    calls = []
    def factory(key, model):
        calls.append((key, model))
        return GeminiPronouncer(key, model, cache_dir=tmp_path / 'pronunciation',
            transport=httpx.MockTransport(lambda r: response()))
    app = create_app(engine, 'pairing-token', catalog=lambda: [{'id':'test:voice','ready':True}],
                     gemini_keys=keys, pronouncer_factory=factory)
    headers = {'Authorization':'Bearer pairing-token'}
    try:
        with TestClient(app) as client:
            assert client.get('/gemini').status_code == 401
            assert client.post('/gemini', headers={**headers,'Origin':'https://example.com'}, json={'api_key':'secret-key-for-test'}).status_code == 403
            value = client.post('/gemini', headers=headers, json={'api_key':'secret-key-for-test'})
            assert value.status_code == 200 and value.json()['key_configured']
            assert 'secret-key-for-test' not in value.text
            assert 'secret-key-for-test' not in client.get('/gemini',headers=headers).text
            invalid = client.post('/gemini', headers=headers, json={'api_key':'sensitive'})
            assert invalid.status_code == 422 and 'sensitive' not in invalid.text
            body = {'paragraphs':[TEXT], 'voice':'test:voice'}
            local = client.post('/jobs',headers=headers,json=body).json()
            wait_for(lambda: engine.get(local['id']).state == 'complete')
            assert calls == []
            test = client.post('/gemini/test',headers=headers,json={'model':DEFAULT_MODEL})
            assert test.status_code == 200 and 'เลเจนดารี' in test.json()['speech']
            cloud = client.post('/jobs',headers=headers,json={**body, 'gemini':{'enabled':True}}).json()
            wait_for(lambda: engine.get(cloud['id']).state == 'complete')
            status = client.get('/jobs/'+cloud['id'],headers=headers)
            assert status.json()['chunks'][0]['text'] == TEXT
            assert 'secret-key-for-test' not in status.text
            assert client.delete('/gemini',headers=headers).json()['key_configured'] is False
            assert not keys.path.exists()
            assert client.post('/jobs',headers=headers,json={**body,'gemini':{'enabled':True}}).status_code == 422
            assert client.post('/jobs',headers=headers,json=body).status_code == 201
    finally:
        engine.close()


def test_cancel_during_cloud_request_discards_audio(tmp_path):
    started, release = threading.Event(), threading.Event()
    class BlockingPronouncer:
        def readings(self, *args):
            started.set()
            release.wait(timeout=3)
            return {"ลอเอล": "คำอ่านใหม่"}
    backend = FakeBackend()
    engine = Engine(backend, tmp_path)
    try:
        old = engine.create([TEXT], 'test:voice', 0, {}, pronouncer=BlockingPronouncer())
        assert started.wait(timeout=2)
        engine.cancel(old.id)
        release.set()
        new = engine.create(['งานใหม่'], 'test:voice', 0, {})
        wait_for(lambda: new.state == 'complete')
        assert old.chunks[0].path is None
        assert backend.calls == 1
    finally:
        release.set()
        engine.close()


@pytest.mark.parametrize('count', [3, 4])
def test_page_batches_are_balanced_and_cover_every_span_once(count):
    segments = [Segment(i // 4, str(i) + "คำอ่าน" * (i % 17 + 2), "") for i in range(100)]
    batches = page_batches(segments, count)
    assert len(batches) == count
    assert [i for b in batches for i in range(b.start, b.end)] == list(range(len(segments)))
    for batch in batches:
        expected = ''.join(('\n\n' if i > batch.start and segments[i].paragraph != segments[i-1].paragraph else '') + segments[i].text for i in range(batch.start, batch.end))
        assert batch.text == expected
    sizes = [sum(len(s.text) for s in segments[b.start:b.end]) for b in batches]
    assert max(sizes) - min(sizes) <= 2 * max(len(s.text) for s in segments)


def test_short_selection_uses_one_batch_and_empty_page_none():
    assert len(page_batches([Segment(i, 'สวัสดี', '') for i in range(8)])) == 1
    assert page_batches([]) == []


@pytest.mark.parametrize('count', [3, 4])
def test_full_page_uses_only_requested_cloud_calls_and_reuses_disk_cache(tmp_path, count):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return response({"replacements": []})
    def provider():
        return GeminiPronouncer('fake-key-for-batching', cache_dir=tmp_path / 'readings', transport=httpx.MockTransport(handler))
    paragraphs = [f'ย่อหน้าที่ {i} ' + 'ลอเอลพบไอเทม Legendary แล้วเปิดหนังสือเก่าอย่างช้า ๆ ' * 3 for i in range(40)]
    engine = Engine(FakeBackend(), tmp_path / 'audio')
    try:
        for replay in range(2):
            job = engine.create(paragraphs, 'test:voice', 0, {}, pronouncer=provider(), pronunciation_batches=count)
            # Only the current batch is prepared, not all page batches up front.
            wait_for(lambda: all(c.path for c in job.chunks[:3]))
            assert len(requests) == (1 if replay == 0 else count)
            for index in range(3, len(job.chunks), 3):
                engine.cursor(job.id, index)
                wait_for(lambda: all(c.path for c in job.chunks[index:index+3]))
            assert job.state == 'complete'
            assert len(requests) == count
            assert engine.snapshot(job.id)['pronunciation'] == {'total_batches':count,'ready_batches':count}
        assert all(len(json.loads(r['contents'][0]['parts'][0]['text'])['text']) > 1500 for r in requests)
    finally:
        engine.close()


def test_first_api_call_interprets_bgm_scenes_and_exposes_bgm_endpoints(tmp_path):
    keys = GeminiKeys(tmp_path / '.gemini.json')
    keys.save('AIza-fake-key-for-bgm-test')
    seen_contexts = []
    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body['contents'][0]['parts'][0]['text'])
        seen_contexts.append(payload.get('context', ''))
        return response({
            "replacements": [{"source": "ลอเอล", "reading": "ลอ เอล"}],
            "scenes": [
                {"anchor": "[P0]", "track": "warm", "tempo": "medium"},
                {"anchor": "[P1]", "track": "romantic", "tempo": "slow"},
                {"anchor": "[P2]", "track": "action", "tempo": "fast"},
            ],
        })
    def factory(key, model):
        return GeminiPronouncer(key, model, cache_dir=tmp_path / 'pronunciation',
                                transport=httpx.MockTransport(handler))
    engine = Engine(FakeBackend(), tmp_path / 'audio')
    app = create_app(engine, 'pairing-token', catalog=lambda: [{'id': 'test:voice', 'ready': True}],
                     gemini_keys=keys, pronouncer_factory=factory)
    headers = {'Authorization': 'Bearer pairing-token'}
    try:
        with TestClient(app) as client:
            bgm_list = client.get('/bgm', headers=headers)
            assert bgm_list.status_code == 200 and len(bgm_list.json()) == 8
            bgm_wav = client.get('/bgm/romantic', headers=headers)
            assert bgm_wav.status_code == 200 and bgm_wav.content[:4] == b'RIFF'
            paragraphs = [
                "ลอเอลยิ้มอย่างอบอุ่นในยามเช้า",
                "ใบหน้าของเธอแดงระเรื่อด้วยความเขินอาย",
                "ทันใดนั้นศัตรูก็พุ่งเข้ามาโจมตีด้วยดาบ!",
            ]
            job = client.post('/jobs', headers=headers, json={
                'paragraphs': paragraphs, 'voice': 'test:voice', 'gemini': {'enabled': True}
            }).json()
            wait_for(lambda: engine.get(job['id']).state == 'complete')
            assert seen_contexts and '[P0]' in seen_contexts[0] and '[P2]' in seen_contexts[0]
            chunks = client.get(f"/jobs/{job['id']}", headers=headers).json()['chunks']
            assert [c['bgm']['track'] for c in chunks] == ['warm', 'romantic', 'action']
            assert [c['bgm']['tempo'] for c in chunks] == ['medium', 'slow', 'fast']
    finally:
        engine.close()
