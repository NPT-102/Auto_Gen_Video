"""Chạy Python của một venv (video-factory, MoneyPrinterTurbo, Pixelle) dù launcher của venv bị Smart App Control chặn.

07/10/2026: Smart App Control bắt đầu chặn MoneyPrinterTurbo/.venv/Scripts/python.exe (launcher của uv, không ký số;
lỗi "An Application Control policy has blocked this file"), 09/10 chặn luôn launcher của video-factory và Pixelle (cùng
một file), trong khi interpreter gốc mà venv trỏ tới (home trong pyvenv.cfg) vẫn chạy được. Không tắt Smart App
Control: launcher bị chặn thì chạy interpreter gốc, nạp site-packages của venv bằng site.addsitedir (xử lý cả file
.pth) rồi chạy script / mã -c / module -m như bình thường.

Dùng từ dòng lệnh (vf-python.cmd làm việc này cho .venv của video-factory):
    <python gốc của venv> -P factory/pyrun.py <venv> -m uvicorn factory.app:app --port 8600
"""

import os
import subprocess
import sys
from functools import cache
from pathlib import Path

BOOT = """import os, runpy, site, sys
site.addsitedir(r'{site}')
sys.prefix = sys.exec_prefix = r'{venv}'
a = sys.argv[1:]
here = os.getcwd() if not a or a[0] in ('-c', '-m') else os.path.dirname(os.path.abspath(a[0]))
if here not in sys.path:
    sys.path.insert(0, here)
if a and a[0] == '-c':
    sys.argv = ['-c', *a[2:]]
    exec(compile(a[1], '<string>', 'exec'), {{'__name__': '__main__'}})
elif a and a[0] == '-m':
    sys.argv = [a[1], *a[2:]]
    runpy.run_module(a[1], run_name='__main__', alter_sys=True)
else:
    sys.argv = a
    runpy.run_path(a[0], run_name='__main__')
"""


def _boot(venv: Path) -> str:
    return BOOT.format(site=venv / "Lib" / "site-packages", venv=venv)


def base_python(venv: Path) -> Path:
    """Interpreter gốc mà venv được tạo từ đó (dòng home trong pyvenv.cfg)."""
    cfg = {k.strip(): v.strip() for k, v in (line.split("=", 1) for line in
                                             (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines() if "=" in line)}
    return Path(cfg["home"]) / "python.exe"


@cache
def venv_python(venv: Path) -> tuple[str, ...]:
    """Tiền tố lệnh để chạy Python của `venv`: (launcher,) nếu chạy được, không thì (interpreter gốc, "-c", BOOT)."""
    launcher = venv / "Scripts" / "python.exe"
    try:
        if subprocess.run([str(launcher), "-c", "pass"], capture_output=True, timeout=60).returncode == 0:
            return (str(launcher),)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return (str(base_python(venv)), "-c", _boot(venv))


if __name__ == "__main__":   # python -P pyrun.py <venv> (-m module | -c code | script.py) [tham số...]
    venv = Path(sys.argv[1]).resolve()
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    exec(compile(_boot(venv), "<pyrun>", "exec"), {"__name__": "__pyrun__"})
