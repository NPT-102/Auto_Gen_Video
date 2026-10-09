@echo off
rem Cai cong cu tu ve anh: ComfyUI portable (card NVIDIA) + model SDXL-Lightning 4 buoc, tai ~9 GB, kiem tra SHA-256.
rem Rot mang thi chay lai: file dang tai do se duoc tai tiep. Chi tiet: setup\cai-comfyui.ps1
title Cai ComfyUI + SDXL-Lightning (dong cua so la dung tai, chay lai se tai tiep)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\cai-comfyui.ps1" %*
echo.
pause
