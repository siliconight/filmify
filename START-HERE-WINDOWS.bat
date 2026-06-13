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

rem ---- Pick the input ----------------------------------------------------------
set "PICK=%~1"
if not defined PICK (
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $f=New-Object System.Windows.Forms.OpenFileDialog; $f.Title='filmify - choose a video clip (Cancel to pick a folder instead)'; $f.Filter='Video files|*.mp4;*.mov;*.mkv;*.avi;*.m4v;*.webm;*.mts|All files|*.*'; if($f.ShowDialog() -eq 'OK'){$f.FileName}"`) do set "PICK=%%I"
)
if not defined PICK (
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $f=New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description='filmify - choose a folder of clips to batch'; if($f.ShowDialog() -eq 'OK'){$f.SelectedPath}"`) do set "PICK=%%I"
)
if not defined PICK (
  echo   Nothing chosen -- closing.
  pause
  exit /b 0
)

if exist "%PICK%\" (
  rem Folder: batch a fast split-screen preview of every clip
  %PY% "%SCRIPT%" "%PICK%" --compare --preview
) else (
  rem Single clip: open the control panel in the browser
  echo.
  echo   Opening the filmify panel in your browser.
  echo   The panel will open in your browser; you can close this window.
  echo.
  rem pythonw runs the panel windowless; fall back to %PY% if absent
  where pythonw >nul 2>nul && (start "" pythonw "%SCRIPT%" "%PICK%" --ui) || (%PY% "%SCRIPT%" "%PICK%" --ui)
)
echo.
pause
