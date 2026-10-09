@echo off
rem Chay Python cua video-factory (.venv) tu thu muc goc du an, tham so nhu python thuong. Vi du:
rem   vf-python.cmd -m factory.status
rem   vf-python.cmd -m factory.try_engine hyperframes content\aws-saa\ep05.json
rem Smart App Control co the chan .venv\Scripts\python.exe (launcher cua uv khong ky so, loi "An Application Control
rem policy has blocked this file") -> khi do chay Python goc ma venv tro toi (dong home trong .venv\pyvenv.cfg) va nap
rem thu vien cua venv qua factory\pyrun.py. Khong can tat Smart App Control.
setlocal
cd /d "%~dp0"
rem in/doc tieng Viet bang UTF-8 du cua so console dung bang ma nao
set "PYTHONUTF8=1"
if not exist ".venv\pyvenv.cfg" (
  echo Chua cai dat: chay cai-dat.cmd truoc.
  exit /b 1
)
".venv\Scripts\python.exe" -c "pass" >nul 2>&1
if errorlevel 1 goto base
".venv\Scripts\python.exe" %*
exit /b %errorlevel%

:base
set "BASE="
for /f "usebackq tokens=1,* delims== " %%a in (".venv\pyvenv.cfg") do if /i "%%a"=="home" set "BASE=%%b\python.exe"
if not exist "%BASE%" (
  echo Khong chay duoc .venv\Scripts\python.exe va khong thay Python goc "%BASE%" - chay lai cai-dat.cmd.
  exit /b 1
)
"%BASE%" -P factory\pyrun.py .venv %*
exit /b %errorlevel%
