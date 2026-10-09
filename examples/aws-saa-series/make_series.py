"""Tạo video cho series AWS SAA bằng chế độ batch của MoneyPrinterTurbo (cli.py).

Chạy trong thư mục này, bằng Python của MoneyPrinterTurbo (trong repo video-factory: ..\\..\\engines\\MoneyPrinterTurbo):
    ..\\MoneyPrinterTurbo\\.venv\\Scripts\\python.exe make_series.py 1
    ..\\MoneyPrinterTurbo\\.venv\\Scripts\\python.exe make_series.py 2-5 9
    ..\\MoneyPrinterTurbo\\.venv\\Scripts\\python.exe make_series.py all

Kịch bản và từ khoá lấy từ episodes.json nên không gọi Gemini; chỉ cần key Pexels.
Video xong được chép vào output/ với tên "Tap-01 - <tiêu đề>.mp4".
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# MoneyPrinterTurbo: MPT_DIR → engines/MoneyPrinterTurbo của repo video-factory (thư mục này là examples/aws-saa-series)
# → thư mục nằm cạnh (cách bố trí ban đầu)
MPT_DIR = Path(os.environ.get("MPT_DIR") or next(
    (p for p in (HERE.parents[1] / "engines" / "MoneyPrinterTurbo", HERE.parent / "MoneyPrinterTurbo") if (p / "cli.py").exists()),
    HERE.parent / "MoneyPrinterTurbo"))
MPT_PYTHON = MPT_DIR / ".venv" / "Scripts" / "python.exe"
OUTPUT_DIR = HERE / "output"

# Cài đặt chung cho mọi tập. Đổi ở đây nếu muốn khác giọng, khung hình, font...
SETTINGS = {
    "video_source": "pexels",
    "video_aspect": "9:16",  # "16:9" nếu làm video YouTube ngang
    "video_concat_mode": "random",
    "video_clip_duration": 4,
    "video_language": "vi-VN",
    "voice_name": "vi-VN-HoaiMyNeural-Female",  # hoặc vi-VN-NamMinhNeural-Male
    "voice_rate": 1.0,
    "voice_volume": 1.0,
    # không dùng kho nhạc có sẵn của MoneyPrinterTurbo: 28/09/2026 một bản bị Content ID nhận, YouTube chặn Short
    "bgm_type": "",
    "bgm_volume": 0.0,
    "subtitle_enabled": True,
    "subtitle_position": "bottom",
    "font_name": "BeVietnamPro-Bold.ttf",  # font mặc định của app thiếu dấu tiếng Việt
    "font_size": 60,
    "stroke_width": 2.0,
    "n_threads": 8,
}


def parse_selection(tokens: list[str], all_eps: list[int]) -> list[int]:
    if [t.lower() for t in tokens] == ["all"]:
        return all_eps
    selected: list[int] = []
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = (int(x) for x in part.split("-", 1))
                selected.extend(range(start, end + 1))
            else:
                selected.append(int(part))
    return list(dict.fromkeys(selected))


def safe_filename(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', " -", text).strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Tạo video series AWS SAA")
    parser.add_argument("episodes", nargs="+", help='số tập, ví dụ: 1 | 2-5 | 1,3,7 | all')
    args = parser.parse_args()

    data = json.loads((HERE / "episodes.json").read_text(encoding="utf-8"))
    episodes = {e["ep"]: e for e in data["episodes"]}
    selected = parse_selection(args.episodes, sorted(episodes))
    missing = [n for n in selected if n not in episodes]
    if missing:
        parser.error(f"không có tập: {missing}")

    tasks = [
        {
            **SETTINGS,
            "video_subject": f"{data['series']} tập {n}: {episodes[n]['title']}",
            "video_script": episodes[n]["script"],
            "video_terms": episodes[n]["terms"],
        }
        for n in selected
    ]
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as manifest:
        json.dump(tasks, manifest, ensure_ascii=False)

    print(f"Tạo {len(tasks)} video: tập {', '.join(map(str, selected))}", flush=True)
    # cli.py in JSON có dấu tiếng Việt ra stdout; không ép UTF-8 thì Windows báo lỗi mã hoá.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            [str(MPT_PYTHON), "cli.py", "--batch-file", manifest.name],
            cwd=MPT_DIR,
            env=env,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    finally:
        os.unlink(manifest.name)

    try:
        summary = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        print(proc.stdout)
        print(f"cli.py thoát với mã {proc.returncode}, không có kết quả JSON")
        return proc.returncode or 1

    OUTPUT_DIR.mkdir(exist_ok=True)
    for task in summary["tasks"]:
        n = selected[task["index"] - 1]
        label = f"Tap-{n:02d} - {safe_filename(episodes[n]['title'])}"
        if task["status"] != "succeeded":
            print(f"LỖI  {label}: bước {task['failed_stage']}: {task['error']}")
            continue
        videos = (task.get("result") or {}).get("videos") or []
        if not videos:
            print(f"LỖI  {label}: không thấy file video trong kết quả")
            continue
        target = OUTPUT_DIR / f"{label}.mp4"
        shutil.copy2(videos[0], target)
        print(f"XONG {target}")

    print(f"{summary['succeeded']}/{summary['total']} video thành công")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
