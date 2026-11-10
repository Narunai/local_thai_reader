"""One persistent, private stdio worker in OmniVoice's isolated environment."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading

from .settings import ROOT, MODEL_DIR

OMNI_STEPS = 32
OMNI_PYTHON = ROOT / ".venv-omni" / "Scripts" / "python.exe"
OMNI_RUNTIME = ROOT / ".venv-omni" / "runtime.json"
OMNI_FILES = (
    "manifest.json", "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
    "audio_tokenizer/config.json", "audio_tokenizer/model.safetensors", "audio_tokenizer/preprocessor_config.json",
)


def installed():
    return OMNI_PYTHON.is_file() and OMNI_RUNTIME.is_file() and all(
        (MODEL_DIR / "omnivoice" / name).is_file() for name in OMNI_FILES)


class OmniProcess:
    def __init__(self, reference):
        self.process = None
        self.log = None
        self.responses = queue.Queue()
        self.metrics = {}
        self.device = "cpu"
        try:
            (ROOT / "cache").mkdir(parents=True, exist_ok=True)
            self.log = (ROOT / "cache" / "omnivoice-worker.log").open("w", encoding="utf-8")
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1", TOKENIZERS_PARALLELISM="false")
            self.process = subprocess.Popen(
                [str(OMNI_PYTHON), "-X", "utf8", "-u", "-m", "app.omni_worker"],
                cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.reader = threading.Thread(target=self._read, daemon=True, name="omnivoice-responses")
            self.reader.start()
            reply = self.request({"action": "load", "reference": reference}, timeout=240)
            self.device = reply["device"]
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.responses.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.responses.put(None)

    def request(self, payload, timeout=180):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError(self._exit_message())
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            reply = self.responses.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise RuntimeError("OmniVoice timed out; try a shorter paragraph") from None
        except (BrokenPipeError, OSError):
            self.close()
            raise RuntimeError("OmniVoice worker disconnected") from None
        if reply is None:
            raise RuntimeError(self._exit_message())
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "OmniVoice failed"))
        self.metrics = reply.get("metrics", {})
        return reply

    def _exit_message(self):
        # Report dependency failures without returning arbitrary worker logs,
        # which can contain the text being read or paths supplied by the user.
        try:
            with (ROOT / "cache" / "omnivoice-worker.log").open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 16384))
                tail = stream.read().decode("utf-8", errors="replace")
            missing = re.search(r"ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'", tail)
            if missing:
                return (f"OmniVoice worker exited: missing module '{missing[1]}' in .venv-omni. "
                        "Run local-tts/setup-omnivoice.ps1")
        except OSError:
            pass
        return "OmniVoice worker exited; see cache/omnivoice-worker.log"

    def synthesize(self, text, output):
        return self.request({"action": "synthesize", "text": text, "output": str(Path(output).resolve())})

    def close(self):
        process = self.process
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
            reader = getattr(self, "reader", None)
            if reader:
                reader.join(timeout=2)
            if process.stdout:
                process.stdout.close()
        if self.log:
            self.log.close()
        self.process = None
