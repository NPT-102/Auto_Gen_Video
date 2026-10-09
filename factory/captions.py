"""Phụ đề karaoke dạng ASS (ffmpeg/libass đốt vào video): chữ trắng, từ đã đọc chuyển vàng, nền mờ phía sau."""

from .narration import build_phrases

HEADER = [
    "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
    "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Cap,Be Vietnam Pro,58,&H0000D7FF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,3,16,0,2,90,90,300,1",
    # nhãn nhỏ phía trên (vd. "HIỆU ỨNG 2 · CÂY CẦU TREO") và tiêu đề lớn của cảnh mở đầu
    "Style: Kicker,Be Vietnam Pro,40,&H0000D7FF,&H0000D7FF,&H00000000,&H96000000,-1,0,0,0,100,100,2,0,3,14,0,8,80,80,190,1",
    "Style: Hook,Be Vietnam Pro,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,3,22,0,8,80,80,300,1",
    "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]


def ts(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def esc(text: str) -> str:
    """Chữ thường → an toàn trong ASS (ngoặc nhọn là thẻ định dạng)."""
    return str(text).replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def karaoke_ass(words: list[dict], overlays: list[tuple[float, float, str, str]] = ()) -> str:
    """words: [{display, start, end, scene, brk}] theo thời gian tuyệt đối.
    overlays: (bắt đầu, kết thúc, style, chữ ASS đã esc — được phép chứa thẻ như \\N, {\\fs48})."""
    events = [f"Dialogue: 1,{ts(a)},{ts(b)},{style},,0,0,0,,{text}" for a, b, style, text in overlays if text and b > a]
    phrases = build_phrases(words, max_words=7)
    for i, p in enumerate(phrases):
        chunk = words[p["from"]: p["to"] + 1]
        text = "".join(
            f"{{\\k{max(1, round(((chunk[k + 1]['start'] if k + 1 < len(chunk) else w['end']) - w['start']) * 100))}}}"
            f"{esc(w['display'])} " for k, w in enumerate(chunk)).strip()
        # giữ cụm thêm 0,25 giây cho kịp đọc, nhưng không đè lên cụm sau (libass sẽ xếp chồng hai dòng)
        end = p["end"] + 0.25 if i + 1 == len(phrases) else min(p["end"] + 0.25, phrases[i + 1]["start"])
        events.append(f"Dialogue: 0,{ts(p['start'])},{ts(max(end, p['start'] + 0.05))},Cap,,0,0,0,,{text}")
    return "\n".join([*HEADER, *events, ""])
