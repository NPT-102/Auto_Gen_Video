#!/usr/bin/env python3
"""Run factory's venv Python from any directory: python3 vf-python.py -m factory.status."""
import subprocess
import sys

from factory.pyrun import python_path, venv_python
from setup.common import ROOT, local_env


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not python_path(ROOT / ".venv").exists():
        print("Factory .venv is missing. Run python3 cai-dat.py first.", file=sys.stderr)
        return 1
    try:
        return subprocess.run([*venv_python(ROOT / ".venv"), *args], cwd=ROOT, env=local_env(ROOT)).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
