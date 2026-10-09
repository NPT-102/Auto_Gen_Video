@echo off
rem Cai dat Video Factory: kiem tra phan mem, tai 3 repo engine, cai thu vien, chep key. Chay lai bao nhieu lan cung duoc.
rem Chi tiet tung buoc: setup\cai-dat.ps1. Chi xem tinh trang: cai-dat.cmd -KiemTra
title Cai dat Video Factory
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\cai-dat.ps1" %*
echo.
pause
