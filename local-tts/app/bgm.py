"""Local background music (BGM) synthesizer and Thai novel context/emotion analyzer."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import soundfile as sf

from .settings import ROOT

BGM_DIR = ROOT / "bgm"
SAMPLE_RATE = 24000
DURATION_SECONDS = 16.0

TRACK_META = {
    "calm": {"name": "สงบผ่อนคลาย", "default_tempo": "slow"},
    "warm": {"name": "อบอุ่นสบายใจ", "default_tempo": "medium"},
    "romantic": {"name": "โรแมนติกหวานซึ้ง", "default_tempo": "slow"},
    "sad": {"name": "เศร้าซึ้งเหงาใจ", "default_tempo": "slow"},
    "mystery": {"name": "ลึกลับน่าค้นหา", "default_tempo": "slow"},
    "tense": {"name": "ตึงเครียดกดดัน", "default_tempo": "medium"},
    "action": {"name": "ต่อสู้เร้าใจ", "default_tempo": "fast"},
    "happy": {"name": "สดใสร่าเริง", "default_tempo": "fast"},
}

TEMPO_META = {
    "slow": ("จังหวะช้า", 0.92),
    "medium": ("จังหวะกลาง", 1.0),
    "fast": ("จังหวะเร็ว", 1.08),
}

MOOD_KEYWORDS: dict[str, list[str]] = {
    "action": [
        "โจมตี", "ดาบ", "ปะทะ", "ฟัน", "ระเบิด", "ศัตรู", "ต่อสู้", "พุ่ง", "สังหาร",
        "เลือด", "สกิล", "เวทมนตร์", "คำราม", "วิ่งหนี", "กระโดด", "หลบ", "ศึก", "สงคราม",
        "ฟาด", "แทง", "ยิง", "พลัง", "ปืน", "มอนสเตอร์", "บอส", "เกราะ", "อาวุธ",
    ],
    "tense": [
        "อันตราย", "ระวัง", "ตึงเครียด", "กดดัน", "ขู่", "เหงื่อ", "สั่น", "กลัว", "หวาดกลัว",
        "คุกคาม", "จ้องเขม็ง", "เย็นยะเยือก", "กับดัก", "ชะงัก", "ตื่นตระหนก", "ตกใจ", "ฉับพลัน",
        "คดี", "ฆาตกร", "วิกฤต", "หัวใจหล่น", "ระแวง", "ตื่นตัว",
    ],
    "romantic": [
        "จูบ", "กอด", "หน้าแดง", "เขิน", "หัวใจเต้น", "รัก", "ริมฝีปาก", "อ้อมกอด",
        "หวาน", "แก้มแดง", "สัมผัส", "แนบชิด", "เรือนร่าง", "เตียง", "ลมหายใจ", "หลงใหล",
        "เสน่ห์", "อ่อนโยน", "สบตา", "ใจเต้น", "หน้าอก", "ผิวขาว", "กระซิบข้างหู", "ร้อนผ่าว",
        "ยั่วยวน", "ลูบไล้", "ออดอ้อน", "ชวน", "สองต่อสอง", "ห้องนอน",
    ],
    "sad": [
        "น้ำตา", "ร้องไห้", "เศร้า", "เสียใจ", "เจ็บปวด", "เหงา", "ห่างเหิน", "จากไป",
        "สูญเสีย", "ทอดถอนใจ", "ถอนหายใจ", "สะอื้น", "โดดเดี่ยว", "อ้างว้าง", "ผิดหวัง", "ขมขื่น",
        "อาลัย", "ลาจาก", "รู้สึกผิด", "แผลในใจ", "มืดมน",
    ],
    "mystery": [
        "ลึกลับ", "ความมืด", "เงา", "ปริศนา", "ความลับ", "กลางคืน", "ป่าลึก", "หมอก",
        "เสียงกระซิบ", "ซ่อน", "แปลกประหลาด", "สงสัย", "ความเงียบ", "วิญญาณ", "ดันเจี้ยน",
        "ความทรงจำ", "ย้อนกลับไป", "ไม่เข้าใจ",
    ],
    "happy": [
        "หัวเราะ", "ร่าเริง", "ดีใจ", "สนุก", "ตลก", "ขำ", "ฉลอง", "ยิ้มกว้าง", "สดใส",
        "เฮฮา", "มีความสุข", "ยินดี", "ตื่นเต้นดีใจ", "ฮ่าๆ", "555", "หยอกล้อ", "แกล้ง",
    ],
    "warm": [
        "ยิ้ม", "อบอุ่น", "ครอบครัว", "เพื่อนสมัยเด็ก", "มิตรภาพ", "อาหาร", "ชา", "กาแฟ",
        "แสงแดด", "สายลม", "เช้า", "บ้าน", "ขอบคุณ", "สบายใจ", "พักผ่อน", "โรงเรียน",
        "ห้องเรียน", "เลิกเรียน", "ม.ปลาย", "ข้างๆ", "สนิท",
    ],
}


@dataclass
class BgmCue:
    track: str = "calm"
    tempo: str = "slow"
    rate: float = 0.92
    label: str = "สงบผ่อนคลาย · จังหวะช้า"

    def to_dict(self) -> dict:
        return {"track": self.track, "tempo": self.tempo, "rate": self.rate, "label": self.label}


def make_cue(track: str, tempo: str | None = None) -> BgmCue:
    if track not in TRACK_META:
        track = "calm"
    if tempo not in TEMPO_META:
        tempo = TRACK_META[track]["default_tempo"]
    tempo_name, rate = TEMPO_META[tempo]
    label = f"{TRACK_META[track]['name']} · {tempo_name}"
    return BgmCue(track=track, tempo=tempo, rate=rate, label=label)


def classify_text_bgm(text: str) -> tuple[str, str, int]:
    """Return (track, tempo, score) for a piece of Thai novel text."""
    scores = {mood: 0 for mood in TRACK_META if mood != "calm"}
    for mood, words in MOOD_KEYWORDS.items():
        for word in words:
            if word in text:
                scores[mood] += 2 if len(word) >= 5 else 1
    best_mood = max(scores, key=lambda k: scores[k])
    best_score = scores[best_mood]
    track = best_mood if best_score > 0 else "calm"

    exclaim = text.count("!") + text.count("！")
    ellipsis = text.count("...") + text.count("…")
    dashes = text.count("—") + text.count("-")
    quotes = text.count("“") + text.count('"') + text.count("「")
    if track == "action" or exclaim >= 2:
        tempo = "fast"
    elif track in ("sad", "mystery") or ellipsis >= 2:
        tempo = "slow"
    elif track == "happy" or (exclaim == 1 and quotes >= 1):
        tempo = "fast" if track in ("happy", "action") else "medium"
    elif track in ("tense", "warm") or dashes >= 2 or quotes >= 2:
        tempo = "medium"
    else:
        tempo = TRACK_META[track]["default_tempo"]
    return track, tempo, best_score


def analyze_segments_bgm(segments, paragraphs: list[str] | None = None) -> list[BgmCue]:
    """Assign smooth scene-aware BGM cues across all segments in a chapter."""
    if not segments:
        return []
    # Score both individual segments and their containing paragraph for richer context
    para_scores: dict[int, tuple[str, str, int]] = {}
    if paragraphs:
        for p_idx, p_text in enumerate(paragraphs):
            para_scores[p_idx] = classify_text_bgm(p_text)

    raw: list[tuple[str, str, int]] = []
    for seg in segments:
        s_track, s_tempo, s_score = classify_text_bgm(seg.text)
        p_track, p_tempo, p_score = para_scores.get(seg.paragraph, (s_track, s_tempo, s_score))
        if s_score >= p_score and s_score > 0:
            raw.append((s_track, s_tempo, s_score))
        else:
            raw.append((p_track, p_tempo, p_score))

    smoothed: list[BgmCue] = []
    current_track = raw[0][0]
    current_tempo = raw[0][1]
    hold = 0
    for i, (track, tempo, score) in enumerate(raw):
        window = raw[max(0, i - 2):min(len(raw), i + 3)]
        window_tracks = [w[0] for w in window if w[2] > 0]
        if score >= 2:
            current_track = track
            current_tempo = tempo
            hold = 4
        elif window_tracks:
            dominant = max(set(window_tracks), key=window_tracks.count)
            current_track = dominant
            current_tempo = next((w[1] for w in window if w[0] == dominant), TRACK_META[dominant]["default_tempo"])
            hold = 3
        elif hold > 0:
            hold -= 1
        else:
            current_track = "calm"
            current_tempo = "slow"
        smoothed.append(make_cue(current_track, current_tempo))
    return smoothed


def apply_scene_cues(chunks, scenes: list[dict]):
    """Apply Gemini contextual scene cues (anchor, track, tempo) onto chunks."""
    if not chunks or not scenes:
        return
    import re
    matched: list[tuple[int, BgmCue]] = []
    search_from = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        anchor = str(scene.get("anchor", "")).strip()
        track = str(scene.get("track", "")).strip().lower()
        tempo = str(scene.get("tempo", "")).strip().lower()
        if track not in TRACK_META:
            continue
        cue = make_cue(track, tempo if tempo in TEMPO_META else None)
        found_idx = None
        para_match = re.match(r"^\[?P?(\d+)\]?", anchor, re.IGNORECASE)
        if para_match:
            target_para = int(para_match.group(1))
            for idx, chunk in enumerate(chunks):
                if chunk.segment.paragraph >= target_para:
                    found_idx = idx
                    break
        if found_idx is None and anchor:
            clean_anchor = re.sub(r"^\[?P?\d+\]?\s*", "", anchor).strip()
            for idx in range(search_from, len(chunks)):
                if clean_anchor and (clean_anchor in chunks[idx].segment.text or chunks[idx].segment.text in clean_anchor):
                    found_idx = idx
                    search_from = idx
                    break
            if found_idx is None and len(clean_anchor) >= 4:
                short = clean_anchor[:12]
                for idx in range(search_from, len(chunks)):
                    if short in chunks[idx].segment.text:
                        found_idx = idx
                        search_from = idx
                        break
        if found_idx is None:
            found_idx = 0 if not matched else min(len(chunks) - 1, matched[-1][0] + max(1, len(chunks) // (len(scenes) + 1)))
        matched.append((found_idx, cue))

    if not matched:
        return
    matched.sort(key=lambda item: item[0])
    active_cue = matched[0][1]
    ptr = 0
    for idx, chunk in enumerate(chunks):
        while ptr < len(matched) and matched[ptr][0] <= idx:
            active_cue = matched[ptr][1]
            ptr += 1
        chunk.bgm = active_cue


def _envelope_loop(signal: np.ndarray, sr: int = SAMPLE_RATE, fade_sec: float = 1.5) -> np.ndarray:
    """Make a signal loop seamlessly by overlapping and crossfading the tail into the head."""
    fade = int(sr * fade_sec)
    if len(signal) <= fade * 2:
        return signal
    body = signal[:-fade].copy()
    tail = signal[-fade:]
    alpha = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    body[:fade] = body[:fade] * alpha + tail * (1.0 - alpha)
    peak = float(np.max(np.abs(body)))
    if peak > 1e-6:
        body = body / peak * 0.35
    return body.astype(np.float32)


def _synth_track(kind: str) -> np.ndarray:
    sr = SAMPLE_RATE
    total_sec = DURATION_SECONDS + 1.5
    t = np.linspace(0.0, total_sec, int(sr * total_sec), endpoint=False, dtype=np.float32)
    out = np.zeros_like(t)

    def pad_chord(freqs: list[float], start: float, end: float, amp: float = 0.25, shimmer: float = 0.2):
        mask = (t >= start) & (t < end)
        lt = t[mask] - start
        dur = max(0.01, end - start)
        env = np.sin(np.pi * lt / dur) ** 0.7
        sig = np.zeros_like(lt)
        for idx, f in enumerate(freqs):
            vib = 1.0 + 0.0015 * np.sin(2 * np.pi * (0.4 + 0.1 * idx) * lt)
            sig += np.sin(2 * np.pi * f * vib * lt)
            sig += shimmer * np.sin(2 * np.pi * (f * 2.0) * lt)
            sig += (shimmer * 0.5) * np.sin(2 * np.pi * (f * 3.0) * lt) * np.exp(-lt * 0.8)
        out[mask] += (sig / max(1, len(freqs))) * env * amp

    def pluck_note(freq: float, start: float, dur: float = 1.8, amp: float = 0.18):
        mask = (t >= start) & (t < start + dur)
        if not np.any(mask):
            return
        lt = t[mask] - start
        env = (1.0 - np.exp(-lt * 45.0)) * np.exp(-lt * 2.4)
        tone = (
            np.sin(2 * np.pi * freq * lt)
            + 0.35 * np.sin(2 * np.pi * freq * 2.0 * lt) * np.exp(-lt * 4.0)
            + 0.12 * np.sin(2 * np.pi * freq * 3.0 * lt) * np.exp(-lt * 7.0)
        )
        out[mask] += tone * env * amp

    if kind == "calm":
        chords = [
            ([174.61, 220.00, 261.63, 329.63], 0.0, 5.0),
            ([146.83, 220.00, 261.63, 349.23], 4.2, 9.2),
            ([196.00, 246.94, 293.66, 392.00], 8.4, 13.4),
            ([174.61, 220.00, 261.63, 329.63], 12.6, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.28, shimmer=0.18)
        for i, note in enumerate([523.25, 659.25, 587.33, 523.25, 440.0, 523.25, 392.0, 440.0]):
            pluck_note(note, i * 2.0 + 0.4, dur=2.2, amp=0.10)

    elif kind == "warm":
        chords = [
            ([130.81, 196.00, 246.94, 329.63], 0.0, 4.8),
            ([164.81, 220.00, 261.63, 392.00], 4.0, 8.8),
            ([174.61, 220.00, 261.63, 349.23], 8.0, 12.8),
            ([196.00, 246.94, 293.66, 392.00], 12.0, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.22, shimmer=0.22)
        arp = [261.63, 329.63, 392.00, 523.25, 392.00, 329.63]
        for step in range(28):
            pluck_note(arp[step % len(arp)], step * 0.6, dur=1.4, amp=0.13)

    elif kind == "romantic":
        chords = [
            ([174.61, 207.65, 261.63, 311.13], 0.0, 4.8),
            ([138.59, 207.65, 261.63, 349.23], 4.0, 8.8),
            ([155.56, 233.08, 311.13, 392.00], 8.0, 12.8),
            ([207.65, 261.63, 311.13, 415.30], 12.0, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.25, shimmer=0.28)
        melody = [523.25, 622.25, 698.46, 622.25, 523.25, 466.16, 523.25, 622.25, 523.25, 415.30]
        for i, note in enumerate(melody):
            pluck_note(note, i * 1.6 + 0.3, dur=2.4, amp=0.14)

    elif kind == "sad":
        chords = [
            ([146.83, 174.61, 220.00, 261.63], 0.0, 5.0),
            ([116.54, 174.61, 220.00, 293.66], 4.2, 9.2),
            ([130.81, 196.00, 261.63, 329.63], 8.4, 13.4),
            ([110.00, 164.81, 220.00, 277.18], 12.6, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.26, shimmer=0.12)
        notes = [440.00, 392.00, 349.23, 329.63, 293.66, 349.23, 329.63, 293.66]
        for i, note in enumerate(notes):
            pluck_note(note, i * 2.0 + 0.5, dur=2.6, amp=0.11)

    elif kind == "mystery":
        chords = [
            ([82.41, 164.81, 246.94, 311.13], 0.0, 5.8),
            ([87.31, 174.61, 246.94, 329.63], 5.0, 11.2),
            ([82.41, 164.81, 233.08, 329.63], 10.4, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.24, shimmer=0.30)
        bells = [659.25, 698.46, 987.77, 659.25, 783.99, 698.46]
        for i, note in enumerate(bells):
            pluck_note(note, i * 2.7 + 0.8, dur=2.8, amp=0.08)

    elif kind == "tense":
        chords = [
            ([65.41, 130.81, 196.00, 207.65], 0.0, 5.5),
            ([61.74, 123.47, 185.00, 196.00], 4.8, 11.0),
            ([65.41, 130.81, 196.00, 207.65], 10.2, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.22, shimmer=0.15)
        pulse_env = (np.sin(2 * np.pi * (t / 0.8)) > 0.75).astype(np.float32)
        pulse = np.sin(2 * np.pi * 58.0 * t) * pulse_env * 0.14
        out += pulse

    elif kind == "action":
        chords = [
            ([110.00, 164.81, 220.00], 0.0, 4.4),
            ([87.31, 130.81, 174.61], 4.0, 8.4),
            ([98.00, 146.83, 196.00], 8.0, 12.4),
            ([82.41, 123.47, 164.81], 12.0, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.20, shimmer=0.25)
        arp = [220.0, 261.63, 329.63, 440.0, 329.63, 293.66, 261.63, 196.0]
        for step in range(68):
            pluck_note(arp[step % len(arp)], step * 0.25, dur=0.35, amp=0.15)

    elif kind == "happy":
        chords = [
            ([196.00, 246.94, 293.66, 392.00], 0.0, 4.4),
            ([164.81, 246.94, 329.63, 392.00], 4.0, 8.4),
            ([130.81, 196.00, 261.63, 329.63], 8.0, 12.4),
            ([146.83, 220.00, 293.66, 369.99], 12.0, 17.5),
        ]
        for freqs, s, e in chords:
            pad_chord(freqs, s, e, amp=0.20, shimmer=0.22)
        notes = [392.00, 493.88, 587.33, 783.99, 659.25, 587.33, 493.88, 587.33]
        for step in range(36):
            pluck_note(notes[step % len(notes)], step * 0.45, dur=0.75, amp=0.14)

    return _envelope_loop(out, sr)


def ensure_bgm_tracks(folder: Path = BGM_DIR) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    catalog = []
    for track_id, meta in TRACK_META.items():
        path = folder / f"{track_id}.wav"
        if not path.is_file():
            samples = _synth_track(track_id)
            sf.write(path, samples, SAMPLE_RATE, subtype="PCM_16")
        catalog.append({
            "id": track_id,
            "name": meta["name"],
            "default_tempo": meta["default_tempo"],
            "ready": True,
        })
    return catalog


def get_bgm_path(track_id: str, folder: Path = BGM_DIR) -> Path | None:
    if track_id not in TRACK_META:
        return None
    ensure_bgm_tracks(folder)
    path = folder / f"{track_id}.wav"
    return path if path.is_file() else None
