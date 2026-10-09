@echo off
rem Bat web Video Factory (cong 8600). Dong cua so nay la tat web.
title Video Factory - cong 8600 (dong cua so nay la tat web)
cd /d "%~dp0"
if not exist ".venv\pyvenv.cfg" (
  echo Chua cai dat: chay cai-dat.cmd truoc.
  pause
  exit /b 1
)
rem mo trinh duyet sau 5 giay, luc server da san sang
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:8600"
rem goi uvicorn qua python -m (Smart App Control chan .venv\Scripts\uvicorn.exe); vf-python.cmd tu chuyen sang Python
rem goc neu launcher .venv\Scripts\python.exe cung bi chan
call "%~dp0vf-python.cmd" -m uvicorn factory.app:app --host 127.0.0.1 --port 8600
echo.
echo Web da dung. Neu bao cong 8600 dang duoc dung thi web van dang chay o cua so khac: mo http://127.0.0.1:8600
pause
