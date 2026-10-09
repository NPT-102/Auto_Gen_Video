"""Giao diện chung của một engine tạo video."""

import os
import subprocess
from pathlib import Path
from typing import Callable

from ..spec import Spec

Log = Callable[[str], None]


class EngineError(RuntimeError):
    def __init__(self, message: str, stdout: str = ""):
        super().__init__(message)
        self.stdout = stdout


class Engine:
    key = ""
    label = ""
    style = ""        # mô tả ngắn phong cách hình ảnh, hiện trên giao diện

    def check(self) -> tuple[bool, str]:
        """(sẵn sàng?, lý do nếu chưa)."""
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        raise NotImplementedError


def utf8_env(**extra: str) -> dict[str, str]:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    # Biến của phiên Claude Code không liên quan tới engine; bỏ đi cho giống khi chạy tay.
    for k in [k for k in env if k.startswith("CLAUDE")]:
        env.pop(k)
    env.update(extra)
    return env


def run(cmd: list[str], cwd: Path, log_file: Path, env: dict | None = None, timeout: int = 3600,
        capture_stdout: bool = False) -> str:
    """Chạy lệnh, ghi log ra file; báo lỗi kèm vài dòng cuối của log nếu thất bại."""
    with open(log_file, "a", encoding="utf-8", errors="replace") as lf:
        lf.write(f"\n$ {' '.join(str(c) for c in cmd)}\n")
        lf.flush()
        proc = subprocess.run(
            [str(c) for c in cmd], cwd=cwd, env=env or utf8_env(), timeout=timeout,
            stdout=subprocess.PIPE if capture_stdout else lf, stderr=lf,
            text=True, encoding="utf-8", errors="replace",
        )
    if proc.returncode != 0:
        tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        raise EngineError(f"lệnh thoát mã {proc.returncode}:\n" + "\n".join(tail),
                          stdout=proc.stdout if capture_stdout else "")
    return proc.stdout if capture_stdout else ""
