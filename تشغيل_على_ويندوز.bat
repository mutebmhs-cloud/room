@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   مساحة الكاتب - نسخة الاختبار المحلية
 echo ================================================
where py >nul 2>nul
if %errorlevel%==0 (
 set "PY=py -3"
) else (
 set "PY=python"
)
%PY% --version
if errorlevel 1 (
 echo Install Python 3.12+ and restart this script.
 pause
 exit /b 1
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
 echo Dependencies installation failed.
 pause
 exit /b 1
)
echo.
echo Generating a SINGLE-USE invite for local test:
%PY% scripts/create_invite.py
echo.
echo Copy the invitation code before closing this window.
echo Open http://127.0.0.1:8000 and register with this code.
echo This local mode is NOT a publicly hosted platform.
start "" "http://127.0.0.1:8000"
%PY% -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
