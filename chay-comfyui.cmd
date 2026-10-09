@echo off
rem Bat ComfyUI (cong 8188) de video-factory ve anh theo cau bang SDXL-Lightning tren GPU. Dong cua so nay la tat.
title ComfyUI - cong 8188 (dong cua so nay la tat)
cd /d "%~dp0"
if not exist "engines\ComfyUI_windows_portable\python_embeded\python.exe" (
  echo Chua cai ComfyUI: bam dup cai-comfyui.cmd truoc.
  pause
  exit /b 1
)
cd /d "%~dp0engines\ComfyUI_windows_portable"
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --listen 127.0.0.1 --port 8188 --disable-auto-launch
echo.
echo ComfyUI da dung. Giao dien: http://127.0.0.1:8188
pause
