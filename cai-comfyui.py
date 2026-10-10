#!/usr/bin/env python3
"""Install optional native ComfyUI. Default: CPU; separate from video setup."""
from setup.comfy import install_main

if __name__ == "__main__":
    raise SystemExit(install_main())
