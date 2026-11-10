"""Keep exact display spans; pronunciation replacements never alter their offsets."""
import re
import unicodedata
from dataclasses import dataclass

import numpy as np
from pythainlp.tokenize import sent_tokenize, word_tokenize

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_DIGITS = ("ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า")
_POSITIONS = ("", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน")


def _six_digit_to_thai(n: int, has_higher_million: bool = False) -> str:
    if n == 0:
        return ""
    s = str(n)
    length = len(s)
    parts: list[str] = []
    for i, ch in enumerate(s):
        d = ord(ch) - 48
        if d == 0:
            continue
        pos = length - 1 - i
        if pos == 1:
            if d == 1:
                parts.append("สิบ")
            elif d == 2:
                parts.append("ยี่สิบ")
            else:
                parts.append(_DIGITS[d] + "สิบ")
        elif pos == 0:
            if d == 1 and (length > 1 or has_higher_million):
                parts.append("เอ็ด")
            else:
                parts.append(_DIGITS[d])
        else:
            parts.append(_DIGITS[d] + _POSITIONS[pos])
    return "".join(parts)


def int_to_thai(n: int) -> str:
    """Convert a non-negative integer into standard Thai reading words."""
    if n < 0:
        return "ลบ" + int_to_thai(-n)
    if n == 0:
        return "ศูนย์"
    groups: list[int] = []
    temp = n
    while temp > 0:
        groups.append(temp % 1_000_000)
        temp //= 1_000_000
    pieces: list[str] = []
    for idx in range(len(groups) - 1, -1, -1):
        val = groups[idx]
        if val > 0:
            pieces.append(_six_digit_to_thai(val, has_higher_million=(idx < len(groups) - 1 and n >= 1_000_000 and val < 10)))
        if idx > 0:
            pieces.append("ล้าน")
    return "".join(pieces)


def _digits_by_char(s: str) -> str:
    return "".join(_DIGITS[ord(c) - 48] for c in s if "0" <= c <= "9")


_INTERJECTION_RE = re.compile(
    r"(?<![ก-ฮะ-ูเ-์])(อ๊ะ|เอ๊ะ|เอ๋|อื้อ|อ๊า|อ่า|ห๊ะ|ฮะ|เฮ้ย|ว้าย|โอ๊ย|อุ๊ย|ว้าว|อ๋อ|อืม|เอ่อ|อึก|ฮึก|ชิ|หึ|เหวอ|เย้|เฮ้อ)\s*([!?！？~～]+)"
)

_PAUSE_MARKER_RE = re.compile(r"((?:\.\s*){2,}\.?|[…⋯]+|[—―–ー]+|--+)")
_STRIP_QUOTES_RE = re.compile(r'^[\s"“”\'‘’\(\[\{（【«‹]+|[\s"“”\'‘’\)\]\}）】»›]+$')


@dataclass
class ProsodicClause:
    text: str
    leading_pause: float = 0.0
    leading_kind: str = ""
    ending: str = "normal"       # "normal" | "ellipsis" | "dash"
    trailing_pause: float = 0.28
    speed: float = 0.94


def expand_maiyamok(text: str) -> str:
    """Expand Thai repetition mark (ๆ) by repeating the preceding Thai word token."""
    def _repl(m: re.Match) -> str:
        prefix = m.group(1)
        count = min(3, len(m.group(2)))
        try:
            tokens = [t for t in word_tokenize(prefix, engine="newmm", keep_whitespace=False) if t.strip()]
        except Exception:
            tokens = [prefix]
        if not tokens:
            return m.group(0)
        word = tokens[-1]
        return prefix + " " + " ".join([word] * count)

    return re.sub(r"([ก-ฮะ-ูเ-์]+)\s*(ๆ+)", _repl, text)


def normalize_thai_numbers(text: str) -> str:
    """Convert numbers, maiyamok (ๆ), interjections, and abbreviations into clear Thai speech."""
    if not text:
        return text
    # Convert Thai digits and superscript/circled digits to ASCII digits
    chars: list[str] = []
    for c in text.translate(_THAI_DIGITS):
        if c.isdigit() and not c.isdecimal():
            try:
                chars.append(str(unicodedata.digit(c)))
                continue
            except ValueError:
                pass
        chars.append(c)
    out = "".join(chars)

    # Collapse 3+ repeated Thai characters (e.g. อ๊าาาา -> อ๊า, อื้อออ -> อื้อ)
    out = re.sub(r"([ก-ฮะ-ูเ-์])\1{2,}", r"\1", out)

    # Expand ไม้ยมก (ๆ) into explicit repeated words so TTS never skips them
    out = expand_maiyamok(out)

    # Give interjections with !/?/~ a clear comma pause while preserving ... and — for prosody
    out = _INTERJECTION_RE.sub(r"\1, ", out)
    out = re.sub(r"[~～]+", " ", out)

    # Expand common Thai abbreviations with dots so TTS does not pause mid-word
    out = re.sub(r"ม\.ต้น", "มอต้น", out)
    out = re.sub(r"ม\.ปลาย", "มอปลาย", out)
    out = re.sub(r"ม\.(\d)", r"มอ \1", out)
    out = re.sub(r"ป\.(\d)", r"ปอ \1", out)
    out = re.sub(r"พ\.ศ\.", "พุทธศักราช ", out)
    out = re.sub(r"ค\.ศ\.", "คริสต์ศักราช ", out)
    # Expand common novel prefixes like Ch.1 / Ch. 12 -> ตอนที่ 1 / ตอนที่ 12
    out = re.sub(r"\bCh\.\s*(\d+(?:\.\d+)?)", r"ตอนที่ \1", out, flags=re.IGNORECASE)
    # Expand 18+ -> 18 บวก
    out = re.sub(r"\b(\d+)\+", r"\1 บวก", out)
    # Expand number ranges like 2-3 or 10–20 -> 2 ถึง 3
    out = re.sub(r"(?<!\d)(\d+)\s*[-–]\s*(\d+)(?!\d)", r"\1 ถึง \2", out)
    # Expand time format like 08.30 น. -> 8 นาฬิกา 30 นาที
    def _replace_time(m: re.Match) -> str:
        hh = int(m.group(1))
        mm = int(m.group(2))
        hour_word = int_to_thai(hh) + "นาฬิกา"
        min_word = (int_to_thai(mm) + "นาที") if mm > 0 else ""
        return f" {hour_word}{min_word} "
    out = re.sub(r"\b([01]?\d|2[0-3])\.([0-5]\d)\s*น\.", _replace_time, out)

    # Replace decimals and integers (with optional commas)
    def _replace_number(m: re.Match) -> str:
        raw_int = m.group(1).replace(",", "")
        frac = m.group(2)
        pct = m.group(3)
        if len(raw_int) > 1 and raw_int.startswith("0") and frac is None:
            word = _digits_by_char(raw_int)
        elif len(raw_int) > 18:
            word = _digits_by_char(raw_int)
        else:
            word = int_to_thai(int(raw_int))
        if frac is not None:
            word = f"{word}จุด{_digits_by_char(frac)}"
        if pct:
            word = f"{word}เปอร์เซ็นต์"
        return f" {word} "

    out = re.sub(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(\s*%)?", _replace_number, out)
    out = re.sub(r" {2,}", " ", out).strip()
    return out if out else text


def _marker_kind(marker: str) -> str:
    if any(c in marker for c in (".", "…", "⋯")):
        return "ellipsis"
    return "dash"


def parse_prosodic_clauses(text: str) -> list[ProsodicClause]:
    """Split text around ellipsis (... / …) and long dashes (— / ― / --) into prosodic clauses."""
    if not text:
        return []
    parts = _PAUSE_MARKER_RE.split(text)
    clauses: list[ProsodicClause] = []
    pending_lead_pause = 0.0
    pending_lead_kind = ""

    idx = 0
    while idx < len(parts):
        chunk = parts[idx]
        marker = parts[idx + 1] if idx + 1 < len(parts) else ""
        idx += 2

        cleaned = _STRIP_QUOTES_RE.sub("", chunk).strip()
        has_speech = any(c.isalnum() or ("\u0e01" <= c <= "\u0e5b") for c in cleaned)

        if not has_speech:
            if marker:
                kind = _marker_kind(marker)
                if clauses:
                    clauses[-1].ending = kind
                    clauses[-1].trailing_pause = max(clauses[-1].trailing_pause, 0.65 if kind == "ellipsis" else 0.60)
                else:
                    pending_lead_kind = kind
                    pending_lead_pause = max(pending_lead_pause, 0.55 if kind == "ellipsis" else 0.50)
            continue

        ending = _marker_kind(marker) if marker else "normal"
        trailing_pause = 0.65 if ending == "ellipsis" else (0.60 if ending == "dash" else 0.28)
        thai_chars = sum(1 for c in cleaned if "\u0e01" <= c <= "\u0e5b" or c.isalnum())
        speed = 0.86 if (ending == "ellipsis" and thai_chars <= 14) else (0.90 if ending in ("ellipsis", "dash") else 0.94)

        clauses.append(
            ProsodicClause(
                text=cleaned,
                leading_pause=pending_lead_pause,
                leading_kind=pending_lead_kind,
                ending=ending,
                trailing_pause=trailing_pause,
                speed=speed,
            )
        )
        pending_lead_pause = 0.0
        pending_lead_kind = ""

    # Cap at 4 clauses per segment by merging middle clauses if extremely fragmented
    while len(clauses) > 4:
        merged = ProsodicClause(
            text=f"{clauses[0].text}, {clauses[1].text}",
            leading_pause=clauses[0].leading_pause,
            leading_kind=clauses[0].leading_kind,
            ending=clauses[1].ending,
            trailing_pause=clauses[1].trailing_pause,
            speed=min(clauses[0].speed, clauses[1].speed),
        )
        clauses = [merged] + clauses[2:]

    return clauses


def wsola_stretch(signal: np.ndarray, sr: int, stretch_start: float = 1.20, stretch_end: float = 1.85) -> np.ndarray:
    """Pitch-preserving WSOLA time-stretching to draw out (ลากเสียง) the trailing word naturally."""
    sig = np.asarray(signal, dtype=np.float32)
    n = len(sig)
    win_size = int(round(0.025 * sr))
    if win_size % 2 == 1:
        win_size += 1
    if n < win_size * 2:
        return sig

    hop_syn = win_size // 2
    search_rad = max(8, int(round(0.0045 * sr)))
    window = np.hanning(win_size).astype(np.float32)

    mean_stretch = 0.5 * (stretch_start + stretch_end)
    max_len = int(n * max(mean_stretch, stretch_end) * 1.35) + win_size * 2
    out = np.zeros(max_len, dtype=np.float32)
    norm = np.zeros(max_len, dtype=np.float32)

    out[:win_size] += sig[:win_size] * window
    norm[:win_size] += window

    pos_ana = 0.0
    out_pos = 0
    prev_actual = 0

    while True:
        progress = min(1.0, pos_ana / max(1.0, float(n - win_size)))
        local_stretch = stretch_start + (stretch_end - stretch_start) * progress
        step_ana = hop_syn / max(0.5, local_stretch)
        pos_ana += step_ana
        target = int(round(pos_ana))
        if target + win_size >= n:
            break

        out_pos += hop_syn
        if out_pos + win_size >= max_len:
            break

        # Align pitch period with natural continuation of previous grain
        natural_next = prev_actual + hop_syn
        lo = max(0, target - search_rad)
        hi = min(n - win_size, target + search_rad)
        best_idx = target
        if hi > lo and natural_next + hop_syn <= n:
            ref = sig[natural_next : natural_next + hop_syn]
            ref_energy = float(np.dot(ref, ref))
            if ref_energy > 1e-7:
                cand_region = sig[lo : hi + hop_syn]
                corr = np.correlate(cand_region, ref, mode="valid")
                if len(corr) > 0:
                    best_idx = lo + int(np.argmax(corr))

        grain = sig[best_idx : best_idx + win_size]
        out[out_pos : out_pos + win_size] += grain * window
        norm[out_pos : out_pos + win_size] += window
        prev_actual = best_idx

    total_len = out_pos + win_size
    valid = norm[:total_len] > 1e-4
    result = np.zeros(total_len, dtype=np.float32)
    result[valid] = out[:total_len][valid] / norm[:total_len][valid]
    return result


def _trim_voiced_bounds(audio: np.ndarray, sr: int) -> tuple[int, int]:
    n = len(audio)
    frame = max(1, int(0.010 * sr))
    if n <= frame * 2:
        return 0, n
    pad = (-n) % frame
    padded = np.pad(audio, (0, pad)) if pad else audio
    rms = np.sqrt(np.mean(padded.reshape(-1, frame) ** 2, axis=1))
    peak = float(np.max(rms)) if len(rms) else 0.0
    if peak < 1e-4:
        return 0, n
    active = np.where(rms > max(peak * 0.045, 1e-4))[0]
    if not len(active):
        return 0, n
    start = max(0, int(active[0] * frame - int(0.015 * sr)))
    end = min(n, int((active[-1] + 1) * frame + int(0.020 * sr)))
    return start, end


def _find_last_word_start(voiced: np.ndarray, sr: int, min_tail_sec: float = 0.26, max_tail_sec: float = 0.52) -> int:
    n = len(voiced)
    if n <= int(0.65 * sr):
        return int(n * 0.25)
    lo = max(int(0.08 * sr), n - int(max_tail_sec * sr))
    hi = max(lo + 1, n - int(min_tail_sec * sr))
    win = max(1, int(0.015 * sr))
    region = voiced[lo:hi]
    if len(region) <= win:
        return lo
    sq = region ** 2
    kernel = np.ones(win, dtype=np.float32) / win
    env = np.convolve(sq, kernel, mode="valid")
    return lo + int(np.argmin(env)) + win // 2


def apply_clause_prosody(audio: np.ndarray, sr: int, clause: ProsodicClause) -> np.ndarray:
    """Apply leading wait, word elongation (ลากเสียง), volume fade-out (ค่อยเบาเสียงลง), and trailing wait."""
    sig = np.asarray(audio, dtype=np.float32)
    if not len(sig):
        return np.zeros(int(sr * max(0.28, clause.trailing_pause)), dtype=np.float32)

    start, end = _trim_voiced_bounds(sig, sr)
    voiced = sig[start:end].copy()
    if not len(voiced):
        return np.zeros(int(sr * max(0.28, clause.trailing_pause)), dtype=np.float32)

    # If the clause starts with "...คำ", give the first syllable a soft hesitant entrance
    if clause.leading_kind == "ellipsis" and len(voiced) > int(0.18 * sr):
        onset_len = min(int(0.18 * sr), len(voiced) // 2)
        onset = wsola_stretch(voiced[:onset_len], sr, stretch_start=1.28, stretch_end=1.05)
        fade_in = np.linspace(0.35, 1.0, len(onset), dtype=np.float32) ** 0.85
        voiced = np.concatenate([onset * fade_in, voiced[onset_len:]])

    if clause.ending == "ellipsis":
        # ลากเสียงคำสุดท้ายก่อน "..." และค่อยๆ เบาเสียงคำนั้นลง
        tail_idx = _find_last_word_start(voiced, sr, min_tail_sec=0.28, max_tail_sec=0.52)
        head = voiced[:tail_idx]
        tail_word = voiced[tail_idx:]
        stretched_tail = wsola_stretch(tail_word, sr, stretch_start=1.22, stretch_end=1.88)
        t_len = len(stretched_tail)
        if t_len > 0:
            # Smooth cosine/power fade-out across the elongated word: 100% -> ~5% -> 0%
            cos_base = np.clip(np.cos(np.linspace(0.0, np.pi * 0.48, t_len, dtype=np.float32)), 0.0, 1.0)
            curve = cos_base ** 1.85
            tip = min(t_len, max(1, int(0.045 * sr)))
            curve[-tip:] *= np.linspace(1.0, 0.0, tip, dtype=np.float32)
            stretched_tail = stretched_tail * curve
        voiced = np.concatenate([head, stretched_tail])
    elif clause.ending == "dash":
        # ขีดยาว (—): ลากหางเสียงเล็กน้อยแล้วเว้นจังหวะรอชัดเจน
        tail_idx = _find_last_word_start(voiced, sr, min_tail_sec=0.18, max_tail_sec=0.34)
        head = voiced[:tail_idx]
        tail_word = voiced[tail_idx:]
        stretched_tail = wsola_stretch(tail_word, sr, stretch_start=1.10, stretch_end=1.35)
        t_len = len(stretched_tail)
        if t_len > 0:
            fade_len = max(1, int(t_len * 0.55))
            curve = np.ones(t_len, dtype=np.float32)
            cos_base = np.clip(np.cos(np.linspace(0.0, np.pi * 0.5, fade_len, dtype=np.float32)), 0.0, 1.0)
            curve[-fade_len:] = cos_base ** 1.15
            stretched_tail = stretched_tail * curve
        voiced = np.concatenate([head, stretched_tail])
    else:
        tip = min(len(voiced), max(1, int(0.025 * sr)))
        voiced[-tip:] *= np.linspace(1.0, 0.0, tip, dtype=np.float32)

    pieces: list[np.ndarray] = []
    if clause.leading_pause > 0:
        pieces.append(np.zeros(int(round(sr * clause.leading_pause)), dtype=np.float32))
    pieces.append(voiced)
    if clause.trailing_pause > 0:
        pieces.append(np.zeros(int(round(sr * clause.trailing_pause)), dtype=np.float32))
    return np.concatenate(pieces)


@dataclass
class Segment:
    paragraph: int
    text: str
    speech: str


def split_exact(text: str, limit: int = 180) -> list[str]:
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    # Token boundaries are advisory. Slice the ORIGINAL text, preserving whitespace.
    boundaries = set()
    for tokenizer in (lambda s: sent_tokenize(s, engine="crfcut"),
                      lambda s: word_tokenize(s, engine="newmm", keep_whitespace=True)):
        try:
            tokens = tokenizer(text)
            position = 0
            for token in tokens:
                found = text.find(token, position)
                if found >= 0:
                    position = found + len(token)
                    boundaries.add(position)
        except (ImportError, LookupError):
            pass
    boundaries.update(m.end() for m in re.finditer(r"(?:\.{2,}|[…⋯.!?。！？—―–]+|--+)(?:[\s\"'”’]*)|\s+", text))
    pieces, start = [], 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            choices = [b for b in boundaries if start + limit // 3 <= b <= end]
            if choices:
                end = max(choices)
            else:
                # Keep combining marks with the preceding Thai character.
                import unicodedata
                while end < len(text) and unicodedata.category(text[end]).startswith("M"):
                    end += 1
        pieces.append(text[start:end])
        start = end
    return pieces


def segment_paragraphs(paragraphs: list[str], start: int, dictionary: dict[str, str]) -> list[Segment]:
    keys = sorted((k for k in dictionary if k), key=len, reverse=True)
    pattern = re.compile("|".join(map(re.escape, keys))) if keys else None
    result = []
    for index in range(start, len(paragraphs)):
        for piece in split_exact(paragraphs[index]):
            speech = pattern.sub(lambda m: dictionary[m.group()], piece) if pattern else piece
            result.append(Segment(index, piece, speech))
    return result
