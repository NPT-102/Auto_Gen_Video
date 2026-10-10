"""Chạy thử một engine ngoài server:  python3 vf-python.py -m factory.try_engine hyperframes content/aws-saa/ep05.json"""

import shutil
import sys
import time
from pathlib import Path

from .config import CACHE_DIR
from .engines import ENGINES
from .spec import load_spec


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    key, spec_path = sys.argv[1], Path(sys.argv[2])
    engine = ENGINES[key]
    ok, why = engine.check()
    if not ok:
        print(f"{key} chưa sẵn sàng: {why}")
        return 1
    workdir = CACHE_DIR / "try" / key
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    t0 = time.time()
    video = engine.render(load_spec(spec_path), workdir, lambda m: print(f"[{time.time() - t0:5.0f}s] {m}", flush=True))
    print(f"XONG {video} sau {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
