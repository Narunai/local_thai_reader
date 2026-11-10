"""Process isolation, shutdown, and cache invalidation without loading a GPU."""
import json
import subprocess
import sys

import pytest

from app import omni_process, backends


@pytest.fixture
def fake_process(tmp_path, monkeypatch):
    script = tmp_path / "worker.py"
    script.write_text('''import json,sys,time
for line in sys.stdin:
    req=json.loads(line)
    if req.get('reference',{}).get('missing'):
        print("ModuleNotFoundError: No module named 'pythainlp'",file=sys.stderr,flush=True)
        sys.exit(1)
    if req.get('text')=='wait': time.sleep(10)
    if req.get('text')=='crash': sys.exit(3)
    error=req.get('text')=='oom' or req.get('reference',{}).get('bad')
    print(json.dumps({'ok':not error,'error':'CUDA out of memory','device':'cuda:0','metrics':{'test':1}}),flush=True)
''', encoding="utf-8")
    original = subprocess.Popen
    children = []
    def spawn(args, **kwargs):
        p = original([sys.executable, "-u", str(script)], **kwargs)
        children.append(p)
        return p
    monkeypatch.setattr(omni_process.subprocess, "Popen", spawn)
    monkeypatch.setattr(omni_process, "ROOT", tmp_path)
    yield children
    for p in children:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)


def test_persistent_worker_and_explicit_unload(fake_process, tmp_path):
    worker = omni_process.OmniProcess({"text":"reference"})
    try:
        worker.synthesize("first", tmp_path / "one.wav")
        worker.synthesize("second", tmp_path / "two.wav")
        assert len(fake_process) == 1
        assert worker.device == "cuda:0"
        assert worker.metrics == {"test":1}
    finally:
        worker.close()
    assert fake_process[0].poll() is not None


def test_load_failure_does_not_leave_worker(fake_process):
    with pytest.raises(RuntimeError, match="out of memory"):
        omni_process.OmniProcess({"bad":True})
    assert fake_process[0].poll() is not None


def test_missing_worker_dependency_is_actionable(fake_process):
    with pytest.raises(RuntimeError, match="missing module 'pythainlp'.*setup-omnivoice"):
        omni_process.OmniProcess({"missing": True})
    assert fake_process[0].poll() is not None


@pytest.mark.skipif(not omni_process.OMNI_PYTHON.is_file(), reason="OmniVoice environment is not installed")
def test_installed_environment_imports_actual_worker():
    result = subprocess.run(
        [str(omni_process.OMNI_PYTHON), "-X", "utf8", "-c",
         "import app.omni_worker; from app.text import parse_prosodic_clauses; "
         "assert parse_prosodic_clauses('ทดสอบการอ่านภาษาไทย')"],
        cwd=omni_process.ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    assert result.returncode == 0, result.stderr[-3000:]


@pytest.mark.parametrize('text,expected', [('oom','out of memory'), ('crash','exited'), ('wait','timed out')])
def test_error_and_timeout_handling(fake_process, text, expected):
    worker = omni_process.OmniProcess({})
    try:
        with pytest.raises(RuntimeError, match=expected):
            worker.request({"action":"synthesize", "text":text}, timeout=.15)
    finally:
        worker.close()
    assert fake_process[0].poll() is not None


def test_fingerprint_tracks_reference_steps_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(backends, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(backends, "OMNI_FILES", ("model.safetensors",))
    monkeypatch.setattr(backends, "OMNI_RUNTIME", tmp_path / "runtime.json")
    (tmp_path / "omnivoice").mkdir()
    model = tmp_path / "omnivoice/model.safetensors"
    model.write_bytes(b"first")
    (tmp_path / "runtime.json").write_text('{}')
    monkeypatch.setattr(backends, "reference", lambda:{"sha256":"voice-one"})
    backend = backends.Backend()
    first = backend.fingerprint("omnivoice:reference")
    monkeypatch.setattr(backends, "reference", lambda:{"sha256":"voice-two"})
    second = backend.fingerprint("omnivoice:reference")
    monkeypatch.setattr(backends, "OMNI_STEPS", 16)
    third = backend.fingerprint("omnivoice:reference")
    model.write_bytes(b"different weight")
    fourth = backend.fingerprint("omnivoice:reference")
    assert len({first,second,third,fourth}) == 4


def test_ready_requires_complete_model_runtime_and_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_process, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(omni_process, "OMNI_PYTHON", tmp_path/'python.exe')
    monkeypatch.setattr(omni_process, "OMNI_RUNTIME", tmp_path/'runtime.json')
    assert not omni_process.installed()
    (tmp_path/'python.exe').touch()
    (tmp_path/'runtime.json').write_text('{}')
    for name in omni_process.OMNI_FILES:
        path=tmp_path/'omnivoice'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.touch()
    assert omni_process.installed()
    monkeypatch.setattr(backends, "reference", lambda:{})
    assert not next(v for v in backends.voices() if v['id']=='omnivoice:reference')['ready']
