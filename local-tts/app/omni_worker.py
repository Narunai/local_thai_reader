"""Offline OmniVoice child. Novel text travels only through private local pipes."""
import json
import socket
import sys
import time

from .settings import MODEL_DIR  # Set all caches to D before importing ML libraries.
from .omni_process import OMNI_STEPS
from .text import apply_clause_prosody, parse_prosodic_clauses


def no_network(*args, **kwargs):
    raise RuntimeError("Network disabled in local OmniVoice worker")


def main():
    wire = sys.stdout
    sys.stdout = sys.stderr  # Keep third-party progress/logging out of the protocol.
    socket.socket.connect = no_network
    socket.create_connection = no_network
    import gc
    import numpy as np
    import soundfile as sf
    import torch
    from accelerate.hooks import remove_hook_from_module
    from omnivoice import OmniVoice

    torch.set_num_threads(4)
    model = prompt = None
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    for line in sys.stdin:
        try:
            request = json.loads(line)
            start = time.perf_counter()
            if device.startswith("cuda"):
                torch.cuda.reset_peak_memory_stats()
            if request["action"] == "load":
                model = OmniVoice.from_pretrained(
                    str(MODEL_DIR / "omnivoice"), device_map=device,
                    dtype=torch.float16 if device.startswith("cuda") else torch.float32,
                    load_asr=False, local_files_only=True, attn_implementation="sdpa",
                )
                if device.startswith("cuda"):
                    remove_hook_from_module(model.audio_tokenizer, recurse=True)
                    model.audio_tokenizer.to("cpu")
                    gc.collect()
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()
                ref = request["reference"]
                prompt = model.create_voice_clone_prompt(ref_audio=ref["path"], ref_text=ref["text"])
            elif request["action"] == "synthesize":
                text = request["text"]
                clauses = parse_prosodic_clauses(text)
                if not clauses:
                    audio = np.zeros(int(model.sampling_rate * 0.45), dtype=np.float32)
                else:
                    rendered = []
                    for clause in clauses:
                        raw = model.generate(
                            text=clause.text, language="th", voice_clone_prompt=prompt,
                            num_step=OMNI_STEPS, speed=clause.speed, pad_duration=0.20,
                        )[0]
                        rendered.append(apply_clause_prosody(raw.astype(np.float32), model.sampling_rate, clause))
                    audio = np.concatenate(rendered) if rendered else np.zeros(4800, dtype=np.float32)
                if not len(audio) or not np.isfinite(audio).all():
                    raise RuntimeError("OmniVoice generated empty or invalid audio")
                sf.write(request["output"], audio, model.sampling_rate, subtype="PCM_16")
            else:
                raise ValueError("Unknown OmniVoice action")
            if device.startswith("cuda"):
                torch.cuda.synchronize()
            metrics = {"elapsed_seconds": round(time.perf_counter() - start, 3),
                       "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 1) if device.startswith("cuda") else 0,
                       "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2, 1) if device.startswith("cuda") else 0}
            response = {"ok": True, "device": device, "metrics": metrics}
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            response = {"ok": False, "error": str(exc)[:1000]}
        wire.write(json.dumps(response, ensure_ascii=False) + "\n")
        wire.flush()


if __name__ == "__main__":
    main()
