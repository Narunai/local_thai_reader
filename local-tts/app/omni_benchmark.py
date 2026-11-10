"""Real GPU benchmark through the same isolated backend used by the API."""
import html
import json
import time
import statistics
import subprocess
import threading

import soundfile as sf
import numpy as np

from .settings import ROOT
from .backends import Backend, reference
from .benchmark import SAMPLES
from .omni_process import OMNI_STEPS


def main():
    folder = ROOT / "reports"
    (folder / "audio").mkdir(parents=True, exist_ok=True)
    backend = Backend()
    rows = []
    report = {"model": "k2-fsa/OmniVoice", "steps": OMNI_STEPS,
              "reference": "Existing synthetic female Vachana reference; listening review pending",
              "reference_sha256": reference()["sha256"], "network_blocked_in_worker": True,
              "manual_listening_review": "pending", "samples": rows}
    stop = threading.Event()
    physical_memory = []
    def monitor():
        while not stop.is_set():
            try:
                result = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    timeout=5, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                physical_memory.append(int(result.strip().splitlines()[0]))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            stop.wait(.5)
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    try:
        start = time.perf_counter()
        backend.load("omnivoice:reference")
        report["load_seconds"] = round(time.perf_counter() - start, 3)
        report["device"] = backend.device
        report["load_metrics"] = backend.model.metrics
        print(f'Loaded in {report["load_seconds"]}s on {backend.device}', flush=True)
        for i, text in enumerate(SAMPLES, 1):
            path = folder / "audio" / f"omnivoice-32steps-{i:02}.wav"
            start = time.perf_counter()
            backend.synthesize("omnivoice:reference", text, path)
            elapsed = time.perf_counter() - start
            samples, rate = sf.read(path)
            assert len(samples) and np.isfinite(samples).all() and np.any(samples != 0)
            seconds = len(samples) / rate
            row = {"sample": i, "text": text, "elapsed_seconds": round(elapsed, 3),
                   "audio_seconds": round(seconds, 3), "rtf": round(elapsed / seconds, 3),
                   "audio": f"audio/{path.name}", **backend.model.metrics}
            rows.append(row)
            print(f'{i:02}: {elapsed:.2f}s / audio {seconds:.2f}s / RTF {elapsed/seconds:.2f} / VRAM {row["peak_allocated_mib"]} MiB', flush=True)
            (folder / "omnivoice.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["warm_mean_seconds"] = round(statistics.mean(r["elapsed_seconds"] for r in rows[1:]), 3)
        report["warm_weighted_rtf"] = round(sum(r["elapsed_seconds"] for r in rows[1:]) / sum(r["audio_seconds"] for r in rows[1:]), 3)
        report["peak_allocated_mib"] = max(r["peak_allocated_mib"] for r in rows)
        report["status"] = "passed"
    finally:
        backend.unload()
        stop.set()
        monitor_thread.join(timeout=6)
        report["peak_nvidia_total_used_mib"] = max(physical_memory, default=None)
        report["nvidia_metric_note"] = "Whole GPU including other processes, sampled every ~0.5 seconds"
        (folder / "omnivoice.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cards = []
    for row in rows:
        comparison = ''
        if row['sample'] == 2 and (folder/'audio/thonburian-48steps-02.wav').exists():
            comparison = '<p>เทียบ Thonburian 48 steps · ข้อความเดียวกัน</p><audio controls preload="none" src="audio/thonburian-48steps-02.wav"></audio>'
        cards.append(f'<article><h2>ข้อความ {row["sample"]}</h2><p>{html.escape(row["text"])}</p><audio controls preload="none" src="{row["audio"]}"></audio><p>สร้าง {row["elapsed_seconds"]} วินาที · เสียง {row["audio_seconds"]} วินาที · RTF {row["rtf"]}</p>{comparison}</article>')
    (folder/'omnivoice.html').write_text('''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ทดลอง OmniVoice</title><style>body{max-width:850px;margin:30px auto;padding:20px;background:#f7f4ec;color:#304b3d;font:16px Tahoma;line-height:1.8}article{padding:22px;margin:18px 0;background:white;border-radius:12px}audio{width:100%}h1{font-size:26px}h2{font-size:19px}</style><h1>OmniVoice · ผู้หญิงอ้างอิง · 32 steps</h1><p>คลิปสร้างบนเครื่องนี้โดยปิดเครือข่ายในตัวรันเสียง ใช้เสียงอ้างอิงสังเคราะห์จาก Vachana เดิม โปรดฟังความเป็นธรรมชาติและคำที่ผิด/ข้าม/ซ้ำด้วยตัวเอง</p>'''+f'<p>โหลดโมเดล {report["load_seconds"]} วินาที · เฉลี่ยหลังอุ่นเครื่อง {report["warm_mean_seconds"]} วินาทีต่อช่วง · RTF {report["warm_weighted_rtf"]} · Peak Torch VRAM {report["peak_allocated_mib"]} MiB</p>'+''.join(cards)+'</html>',encoding='utf-8')


if __name__ == "__main__":
    main()
