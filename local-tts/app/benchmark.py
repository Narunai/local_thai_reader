import argparse
import html
import json
import socket
import subprocess
import time
from pathlib import Path

import soundfile as sf
from .settings import ROOT, prepare, VOICE_DIR
from .backends import Backend, voices

SAMPLES = [
    "สายลมอ่อนพัดผ่านหน้าต่าง เธอเปิดหนังสือเล่มเก่าอย่างช้า ๆ และยิ้มให้กับเรื่องราวที่กำลังจะเริ่มต้น",
    "“เจ้ากลับมาแล้วหรือ” หญิงสาวเอ่ยถามด้วยน้ำเสียงแผ่วเบา ก่อนวางถ้วยชาลงบนโต๊ะไม้",
    "“ข้าจะไม่ยอมแพ้!” เขาตะโกน พลางยกดาบขึ้นป้องกันการโจมตีจากศัตรูเบื้องหน้า",
    "กริดหันไปหาลอเอล ขณะที่จิสึกะและยูเฟอมินากำลังเดินผ่านประตูเมืองเข้ามาพร้อมกัน",
    "ตอนที่ 1,221 เขาได้รับเงิน 12,500 เหรียญ และค่าประสบการณ์เพิ่มขึ้น 25 เปอร์เซ็นต์",
    "เวลา 08.30 น. วันที่ 9 พฤศจิกายน พ.ศ. 2569 เธอออกเดินทางจากกรุงเทพฯ",
    "ไอเทมระดับ Legendary ชิ้นนี้มีค่า HP เพิ่มขึ้น และช่วยลดระยะเวลา Cooldown ของสกิล",
    "ฟ้าร้องครืน ฝนกระหน่ำหนักขึ้นทุกขณะ แต่แสงจากกระท่อมหลังเล็กยังคงส่องสว่างอยู่กลางป่า",
    "เขาเงียบไปนาน… แล้วจึงตอบว่า “ไม่เป็นไร ข้ารอได้” พร้อมส่งรอยยิ้มให้คนตรงหน้า",
    "หนึ่ง สอง สาม สี่ ห้า สิบ ยี่สิบ หนึ่งร้อย หนึ่งพัน และหนึ่งหมื่น เสียงนับดังขึ้นอย่างสม่ำเสมอ",
    "เธอค่อย ๆ หยิบจดหมายออกมาอ่านอีกครั้ง ทุกตัวอักษรยังคงชัดเจน แม้กระดาษจะเก่าและเปลี่ยนเป็นสีเหลืองแล้วก็ตาม",
    "เมื่อการเดินทางสิ้นสุดลง เขาจึงได้รู้ว่าสิ่งสำคัญที่สุด คือมิตรภาพและความทรงจำที่ทุกคนสร้างขึ้นร่วมกัน",
]


def offline_socket(*args, **kwargs):
    raise RuntimeError("Network disabled during offline benchmark")


def make_reference():
    prepare()
    backend = Backend()
    text = SAMPLES[0]
    backend.synthesize("vachana:th_f_1", text, VOICE_DIR / "reference.wav")
    backend.unload()
    (VOICE_DIR / "reference.json").write_text(json.dumps({
        "file": "reference.wav", "text": text,
        "source": "Locally synthesized by this project using VIZINTZOR/VachanaTTS th_f_1; no human voice recording imported",
        "license": "Synthetic reference generated using the MIT-labelled VachanaTTS weights; retain upstream attribution",
        "description": "Synthetic female reference; evaluate naturalness by listening, not a studio narrator recording"
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def benchmark(selected: list[str], offline: bool):
    prepare()
    report_dir = ROOT / "reports"
    audio_dir = report_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    if offline:
        socket.create_connection = offline_socket
        socket.socket.connect = offline_socket
    rows = []
    backend = Backend()
    for voice in selected:
        print(f"Benchmark: {voice}", flush=True)
        backend.unload()
        for index, text in enumerate(SAMPLES):
            file = audio_dir / f"{voice.replace(':','-')}-{index+1:02}.wav"
            start = time.perf_counter()
            try:
                backend.synthesize(voice, text, file)
                elapsed = time.perf_counter() - start
                seconds = sf.info(file).duration
                peak = None
                if "torch" in __import__('sys').modules:
                    import torch
                    if torch.cuda.is_available():
                        peak = round(torch.cuda.max_memory_allocated() / 1024**2, 1)
                row = {"voice": voice, "sample": index+1, "text": text, "elapsed_seconds": round(elapsed, 3),
                       "audio_seconds": round(seconds, 3), "rtf": round(elapsed / max(seconds, .001), 3),
                       "device": backend.device, "peak_torch_vram_mib": peak,
                       "audio": f"audio/{file.name}", "manual_pronunciation_review": "pending"}
                print(f"  {index+1:02}: {elapsed:.2f}s, audio={seconds:.2f}s, RTF={row['rtf']}", flush=True)
            except Exception as exc:
                row = {"voice": voice, "sample": index+1, "error": str(exc), "text": text}
                print(f"  FAILED: {exc}", flush=True)
                rows.append(row)
                break
            rows.append(row)
        (report_dir / "benchmark.json").write_text(json.dumps({"offline_network_blocked": offline, "samples": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    backend.unload()
    render_report(rows, selected)


def render_report(rows: list[dict], selected: list[str]):
    report_dir = ROOT / "reports"
    cards = []
    for row in sorted(rows, key=lambda r:r['sample']):
        audio = f'<audio controls preload="none" src="{row["audio"]}"></audio>' if "audio" in row else html.escape(row["error"])
        fields = '<div class="fields"><label>ความเพราะ 1–5<input data-field="naturalness" type="number" min="1" max="5"></label><label>คำผิด<input data-field="wrong_words" type="number" min="0"></label><label>คำข้าม<input data-field="skipped_words" type="number" min="0"></label><label>คำซ้ำ<input data-field="repeated_words" type="number" min="0"></label></div><label>คำที่อ่านผิด / ความเห็น<textarea data-field="notes" rows="2"></textarea></label>'
        cards.append(f'<article data-voice="{html.escape(row["voice"])}" data-sample="{row["sample"]}"><h2>{html.escape(row["voice"])} · {row["sample"]}</h2><p>{html.escape(row["text"])}</p>{audio}<small>RTF: {row.get("rtf", "—")} · เวลา: {row.get("elapsed_seconds", "—")} วินาที</small>{fields}</article>')
    summary = []
    for voice in selected:
        samples = [r for r in rows if r['voice']==voice and 'rtf' in r]
        if samples:
            warm = [r for r in samples if r['sample']>1] or samples
            summary.append(f'<tr><td>{html.escape(voice)}</td><td>{samples[0]["elapsed_seconds"]:.2f}</td><td>{sum(r["elapsed_seconds"] for r in warm)/len(warm):.2f}</td><td>{max(r.get("peak_torch_vram_mib") or 0 for r in samples):.0f}</td></tr>')
    options = '<option value="all">ทุกข้อความ</option>' + ''.join(f'<option value="{i}">ข้อความที่ {i}</option>' for i in range(1,13))
    data = json.dumps(rows, ensure_ascii=False).replace('<','\\u003c')
    (report_dir / "compare.html").write_text('<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>เปรียบเทียบเสียงนิยาย</title><style>body{font:15px Tahoma;background:#f8f6ef;color:#344b3c;max-width:900px;margin:32px auto;padding:20px}article{background:white;padding:22px;margin:16px 0;border-radius:12px}h1{font-size:28px}h2{font-size:17px}p{line-height:1.9}audio,textarea{width:100%}small{display:block;margin:12px 0;color:#777}label{display:block;font-size:12px;color:#777;margin-top:12px}.fields{display:flex;gap:16px;flex-wrap:wrap}.fields input{display:block;width:90px}input,textarea,select,button{font:inherit;border:1px solid #d7d3c6;border-radius:5px;padding:8px;background:#fffdf8}button{cursor:pointer;background:#344b3c;color:white;margin-left:8px}table{width:100%;border-collapse:collapse;font-size:12px}td,th{text-align:left;padding:12px 6px;border-bottom:1px solid #ddd}[hidden]{display:none}</style><h1>ฟังเสียง แล้วเลือกผู้เล่าของคุณ</h1><p>ข้อความเดียวกัน 12 ชุดจากโมเดลบนเครื่องนี้ คะแนนความเพราะและคำผิดให้คุณเป็นผู้ฟังและบันทึกเอง ข้อมูลประเมินเก็บในเบราว์เซอร์นี้และดาวน์โหลดเป็น JSON ได้ ไม่มีการส่งออกไปภายนอก</p><table><thead><tr><th>เสียง</th><th>รอบแรก (วินาที)</th><th>เฉลี่ยรอบพร้อม (วินาที)</th><th>Peak Torch VRAM (MiB)</th></tr></thead><tbody>' + ''.join(summary) + '</tbody></table><p>รอบแรกรวมเวลาโหลดโมเดล; RTF ต่ำกว่า 1 = สร้างเร็วกว่าความยาวเสียง การประเมินนี้ใช้เสียงอ้างอิงสังเคราะห์จาก Vachana</p><label for="sample">ฟังเปรียบเทียบข้อความ</label><select id="sample">' + options + '</select><button id="export-review">ดาวน์โหลดผลฟัง</button>' + ''.join(cards) + '<script id="benchmark-data" type="application/json">' + data + '</script><script src="compare.js"></script></html>', encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", nargs="+")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--make-reference", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if args.make_reference:
        make_reference()
    elif args.render_only:
        rows = json.loads((ROOT / 'reports' / 'benchmark.json').read_text(encoding='utf-8'))['samples']
        render_report(rows, list(dict.fromkeys(row['voice'] for row in rows)))
    else:
        benchmark(args.voices or [v['id'] for v in voices() if v['ready']], args.offline)
