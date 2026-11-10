import os
import secrets
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("NOVEL_TTS_HOME", Path(__file__).resolve().parents[1])).resolve()
MODEL_DIR = ROOT / "models"
VOICE_DIR = ROOT / "voices"
CACHE_DIR = ROOT / "cache"
CACHE_HOME = Path(os.environ.get("NOVEL_CACHE_HOME", "D:/AI_Cache")).resolve()
for name, folder in {
    "HF_HOME": "huggingface", "HF_HUB_CACHE": "huggingface/hub",
    "HUGGINGFACE_HUB_CACHE": "huggingface/hub", "TORCH_HOME": "torch",
    "TORCHINDUCTOR_CACHE_DIR": "torch/inductor", "TRITON_CACHE_DIR": "triton",
    "NUMBA_CACHE_DIR": "numba", "MPLCONFIGDIR": "matplotlib",
    "XDG_CACHE_HOME": "xdg", "PIP_CACHE_DIR": "pip",
    "PYTHONPYCACHEPREFIX": "pycache", "TEMP": "temp", "TMP": "temp",
}.items():
    os.environ[name] = str(CACHE_HOME / folder)
(CACHE_HOME / "temp").mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(CACHE_HOME / "temp")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def prepare() -> str:
    for folder in (MODEL_DIR, VOICE_DIR, CACHE_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    token_file = ROOT / ".token"
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return token_file.read_text(encoding="utf-8").strip()
