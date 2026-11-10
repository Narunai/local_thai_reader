"""Lazy, offline-only loaders. Exactly one voice/model is resident at a time."""
import gc
import hashlib
import importlib.util
import json
import sys
import wave
import unicodedata
from pathlib import Path

from .settings import ROOT, MODEL_DIR, VOICE_DIR
from .omni_process import OmniProcess, installed as omni_installed, OMNI_STEPS, OMNI_FILES, OMNI_RUNTIME
from .text import apply_clause_prosody, normalize_thai_numbers, parse_prosodic_clauses

F5_MODELS = {
    "thonburian": ("biodatlab/ThonburianTTS", "megaF5/mega_f5_last.safetensors", "megaF5/mega_vocab.txt"),
    "openjai": ("JTS-AI/OpenJaiTTS-v1.0", "model.pt", "vocab.txt"),
}
F5_NFE_STEPS = 48


def reference() -> dict:
    path = VOICE_DIR / "reference.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    audio = (VOICE_DIR / data.get("file", "reference.wav")).resolve()
    if VOICE_DIR not in audio.parents or not audio.is_file() or not data.get("text") or not data.get("license"):
        return {}
    data["path"] = str(audio)
    data["sha256"] = hashlib.sha256(audio.read_bytes()).hexdigest()
    return data


def voices() -> list[dict]:
    result = []
    ready = omni_installed() and bool(reference())
    result.append({"id": "omnivoice:reference", "name": "OmniVoice · ผู้หญิงอ้างอิง · 32 steps",
                   "ready": ready, "device": "cuda/cpu", "license": "CC BY-NC",
                   "reason": "" if ready else "เรียก setup-omnivoice.ps1 และเตรียมเสียงอ้างอิง"})
    for name in ("th_f_1", "th_f_2"):
        files = [MODEL_DIR / "vachana" / f"{name}.onnx", MODEL_DIR / "vachana" / "speaker_config.json"]
        ready = all(f.is_file() for f in files) and importlib.util.find_spec("vachanatts") is not None
        result.append({"id": f"vachana:{name}", "name": f"Vachana · ผู้หญิง {name[-1]}", "ready": ready,
                       "device": "cpu", "reason": "" if ready else "เรียก setup.ps1 เพื่อดาวน์โหลดเสียง", "license": "MIT (model card)"})
    for name, (repo, checkpoint, vocab) in F5_MODELS.items():
        files = [MODEL_DIR / name / checkpoint, MODEL_DIR / name / vocab, MODEL_DIR / "vocos" / "config.yaml", MODEL_DIR / "vocos" / "pytorch_model.bin"]
        ready = all(f.is_file() for f in files) and bool(reference()) and (ROOT / "vendor" / "thonburian-tts" / "flowtts").is_dir() and importlib.util.find_spec("f5_tts") is not None
        result.append({"id": f"{name}:reference", "name": "Thonburian · เสียงอ้างอิง" if name == "thonburian" else "OpenJai · เสียงอ้างอิง",
                       "ready": ready, "device": "cuda/cpu", "reason": "" if ready else ("ต้องได้รับสิทธิ์เข้าถึง OpenJai บน Hugging Face แล้วติดตั้ง F5 และเสียงอ้างอิง" if name == "openjai" else "ต้องติดตั้ง F5 และเตรียม reference.json + เสียงที่มีสิทธิ์ใช้"),
                       "license": "CC BY-NC-SA 4.0" if name == "thonburian" else "CC BY-NC 4.0"})
    return result


class Backend:
    def __init__(self):
        self.current = ""
        self.model = None
        self.device = "cpu"

    def interrupt(self):
        # Called only on server shutdown, to unblock an isolated inference.
        if isinstance(self.model, OmniProcess) and self.model.process and self.model.process.poll() is None:
            self.model.process.terminate()

    def unload(self):
        if isinstance(self.model, OmniProcess):
            self.model.close()
        self.model = None
        self.current = ""
        gc.collect()
        if "torch" in sys.modules:
            torch = sys.modules["torch"]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def fingerprint(self, voice: str) -> str:
        family, speaker = voice.split(":")
        if family == "omnivoice":
            paths = [MODEL_DIR / family / f for f in OMNI_FILES] + [OMNI_RUNTIME]
            return json.dumps(["omnivoice-local-v4", voice, OMNI_STEPS, "th", reference(),
                               [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]], sort_keys=True)
        paths = [MODEL_DIR / "vachana" / f"{speaker}.onnx", MODEL_DIR / "vachana" / "speaker_config.json"] if family == "vachana" else [MODEL_DIR / family / f for f in F5_MODELS[family][1:]]
        stamp = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
        identity = ["novel-tts-v5", voice, stamp, reference() if family != "vachana" else None]
        if family != "vachana":
            identity.append({"nfe_step": F5_NFE_STEPS})
        return json.dumps(identity, sort_keys=True)

    def load(self, voice: str):
        if self.current == voice:
            return
        self.unload()
        family, speaker = voice.split(":")
        if family == "vachana":
            from vachanatts.voice import Voice
            self.model = Voice.load(str(MODEL_DIR / "vachana" / f"{speaker}.onnx"), str(MODEL_DIR / "vachana" / "speaker_config.json"))
            self.device = "cpu"
        elif family == "omnivoice":
            if not omni_installed() or not reference():
                raise RuntimeError("เรียก local-tts/setup-omnivoice.ps1 ก่อนใช้ OmniVoice")
            self.model = OmniProcess(reference())
            self.device = self.model.device
        else:
            import torch
            sys.path.insert(0, str(ROOT / "vendor" / "thonburian-tts"))
            from flowtts.inference import FlowTTSPipeline, ModelConfig, AudioConfig
            from flowtts.load_flowtts import FlowTTS
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            _, checkpoint, vocab = F5_MODELS[family]
            config = ModelConfig(language="th", model_type="F5", checkpoint=str(MODEL_DIR / family / checkpoint),
                                 vocab_file=str(MODEL_DIR / family / vocab), vocoder="vocos", device=self.device)
            model = FlowTTS(language="th", model_type="F5", checkpoint=config.checkpoint,
                            vocab_file=config.vocab_file, vocoder_name="vocos", device=self.device,
                            local_path=str(MODEL_DIR / "vocos"))
            self.model = FlowTTSPipeline(model=model, model_config=config,
                audio_config=AudioConfig(nfe_step=F5_NFE_STEPS), temp_dir=str(ROOT / "cache" / "f5-temp"))
        self.current = voice

    def synthesize(self, voice: str, text: str, output: Path):
        self.load(voice)
        text = normalize_thai_numbers(text)
        if voice.startswith("vachana:"):
            from vachanatts.config import SpeechConfig
            from vachanatts.text_cleaner import clean_text
            from pythainlp import word_tokenize
            import numpy as np
            import soundfile as sf
            # Upstream treats superscript/circled digits as int()-compatible.
            # Normalize those digits only in speech; display text stays exact.
            text = ''.join(str(unicodedata.digit(c)) if c.isdigit() and not c.isdecimal() else c for c in text)
            # Vachana's cleaner removes separators such as --- / *** / “”.
            # Its g2p([]) dereferences sentence[0], so check the same cleaned
            # token stream before invoking synthesis. Do not swallow IndexError
            # from real words or from the ONNX model.
            cleaned = clean_text(text)
            tokens = word_tokenize(cleaned)
            clauses = parse_prosodic_clauses(text) if tokens else []
            rendered = []
            rate = self.model.config.sample_rate
            for clause in clauses:
                c_cleaned = clean_text(clause.text)
                if not word_tokenize(c_cleaned):
                    continue
                length_scale = 1.12 if clause.ending == "ellipsis" else 1.04
                c_chunks = list(self.model.synthesize(clause.text, SpeechConfig(volume=1.0, length_scale=length_scale)))
                if c_chunks:
                    rate = c_chunks[0].sample_rate
                    raw_audio = np.concatenate([c.audio_float_array for c in c_chunks])
                    rendered.append(apply_clause_prosody(raw_audio, rate, clause))
            if rendered:
                sf.write(output, np.concatenate(rendered), rate, subtype="PCM_16")
            elif not any(c.isalnum() for c in cleaned):
                sf.write(output, np.zeros(round(rate * .2)), rate, subtype="PCM_16")
            else:
                raise RuntimeError("Vachana ไม่พบหน่วยเสียงสำหรับข้อความนี้")
        elif voice.startswith("omnivoice:"):
            self.model.synthesize(text, output)
        else:
            ref = reference()
            self.model(text=text, ref_voice=ref["path"], ref_text=ref["text"], output_file=str(output), speed=1.0)
