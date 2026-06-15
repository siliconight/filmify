@echo off
setlocal enabledelayedexpansion
rem START HERE (Windows) -- double-click me.
rem First run: I set up FFmpeg if needed (with your OK), then a file picker
rem appears. Pick a clip to open the filmify control panel, or run me with a
rem folder dragged onto my icon to batch-preview a whole shoot.

set "SCRIPT=%~dp0filmify.py"

rem ---- Python ----------------------------------------------------------------
rem Find a working Python; if none, offer to download and install the official
rem python.org build automatically (per-user, no admin, adds itself to PATH).
set "PY="
where py >nul 2>nul && ( py --version >nul 2>nul && set "PY=py" )
if not defined PY ( where python >nul 2>nul && ( python --version >nul 2>nul && set "PY=python" ) )

if not defined PY (
  echo.
  echo   filmify needs Python ^(a free, open-source tool it runs on^).
  echo   I can download and install the official version from python.org
  echo   ^(about 25 MB, just for you -- no admin needed^).
  echo.
  choice /m "  Download and install Python now"
  if errorlevel 2 (
    echo   OK -- install Python yourself from https://www.python.org/downloads/
    echo   ^(tick "Add python.exe to PATH"^), then run me again.
    pause
    exit /b 1
  )
  echo   downloading Python 3.12.10...
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile \"$env:TEMP\filmify_py.exe\""
  if not exist "%TEMP%\filmify_py.exe" (
    echo   Download failed. Check your internet connection, or install Python
    echo   yourself from https://www.python.org/downloads/ and run me again.
    pause
    exit /b 1
  )
  echo   installing Python ^(a progress window will appear^)...
  "%TEMP%\filmify_py.exe" /passive InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
  del "%TEMP%\filmify_py.exe" >nul 2>nul
  rem PATH was updated for new processes; find python in this session too
  where py >nul 2>nul && ( py --version >nul 2>nul && set "PY=py" )
  if not defined PY ( where python >nul 2>nul && ( python --version >nul 2>nul && set "PY=python" ) )
  if not defined PY (
    rem fall back to the standard per-user install location
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
      if exist "%%D\python.exe" set "PY=%%D\python.exe"
    )
  )
  if not defined PY (
    echo.
    echo   Python was installed, but this window needs a restart to see it.
    echo   Please close this window and double-click filmify again.
    echo.
    pause
    exit /b 1
  )
  echo   Python ready.
)

rem ---- FFmpeg ----------------------------------------------------------------
set "NEEDFF="
if not exist "%~dp0ffmpeg.exe" ( where ffmpeg >nul 2>nul || set "NEEDFF=1" )
if not exist "%~dp0ffprobe.exe" ( where ffprobe >nul 2>nul || set "NEEDFF=1" )
if defined NEEDFF (
  echo.
  echo   filmify needs FFmpeg ^(the free, open-source video engine^).
  echo   I can download the official Windows build from gyan.dev
  echo   ^(the build linked from ffmpeg.org^) -- about 90 MB, saved next
  echo   to this script. Nothing installs system-wide.
  echo.
  choice /m "  Download now"
  if errorlevel 2 (
    echo   OK -- install FFmpeg yourself and run me again.
    pause
    exit /b 1
  )
  echo   downloading...
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile \"$env:TEMP\filmify_ff.zip\""
  if not exist "%TEMP%\filmify_ff.zip" (
    echo   Download failed. Check your internet connection, or install
    echo   FFmpeg yourself: https://ffmpeg.org
    pause
    exit /b 1
  )
  echo   unpacking...
  powershell -NoProfile -Command "Expand-Archive -Force \"$env:TEMP\filmify_ff.zip\" \"$env:TEMP\filmify_ff\""
  powershell -NoProfile -Command "Get-ChildItem -Recurse \"$env:TEMP\filmify_ff\" -Include ffmpeg.exe,ffprobe.exe | Copy-Item -Destination '%~dp0'"
  del "%TEMP%\filmify_ff.zip" >nul 2>nul
  rmdir /s /q "%TEMP%\filmify_ff" >nul 2>nul
  "%~dp0ffmpeg.exe" -version >nul 2>nul
  if not %errorlevel%==0 (
    echo   FFmpeg downloaded but won't run -- please install it yourself
    echo   from https://ffmpeg.org and run me again.
    pause
    exit /b 1
  )
  echo   FFmpeg ready.
)

rem ---- Launch ------------------------------------------------------------------
rem Panel-first: open straight to the import panel. Keep a visible window so
rem the user always has a signal it's running and can read any error.
set "PICK=%~1"
if "%PICK%"=="--quiet" set "PICK="

if defined PICK if exist "%PICK%\" (
  rem Folder dragged on: batch a fast split-screen preview
  %PY% "%SCRIPT%" "%PICK%" --compare --preview
  echo.
  pause
  exit /b 0
)

echo.
echo   Starting filmify... your web browser will open in a moment.
echo   Keep this window open while you work. Close it when you're done.
echo.
if defined PICK (
  %PY% "%SCRIPT%" "%PICK%" --ui
) else (
  %PY% "%SCRIPT%" --ui
)
if not %errorlevel%==0 (
  echo.
  echo   filmify stopped unexpectedly. The message above explains why.
  echo.
  pause
)
exit /b 0
