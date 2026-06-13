@echo off
setlocal
rem START HERE (Windows) — double-click me.
rem First run: I set up FFmpeg if needed (with your OK), then a file picker
rem appears. Pick a clip to open the filmify control panel, or run me with a
rem folder dragged onto my icon to batch-preview a whole shoot.

set "SCRIPT=%~dp0filmify.py"

rem ---- Python ----------------------------------------------------------------
where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py" ) else ( set "PY=python" )
%PY% --version >nul 2>nul
if not %errorlevel%==0 (
  echo.
  echo   Python was not found. Install it from https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" during install, then run me again.
  echo.
  pause
  exit /b 1
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
rem Panel-first: open straight to the import panel. The user picks or drops
rem a clip from inside it (matches the Mac flow). A dragged file/folder still
rem works as a shortcut.
set "PICK=%~1"
if "%PICK%"=="--quiet" set "PICK="

if defined PICK (
  if exist "%PICK%\" (
    rem Folder dragged on: batch a fast split-screen preview
    %PY% "%SCRIPT%" "%PICK%" --compare --preview
    echo.
    pause
    exit /b 0
  )
)

rem Open the panel windowless (pythonw); the browser is the whole UI.
if defined PICK (
  where pythonw >nul 2>nul && (start "" pythonw "%SCRIPT%" "%PICK%" --ui) || (start "" %PY% "%SCRIPT%" "%PICK%" --ui)
) else (
  where pythonw >nul 2>nul && (start "" pythonw "%SCRIPT%" --ui) || (start "" %PY% "%SCRIPT%" --ui)
)
exit /b 0
