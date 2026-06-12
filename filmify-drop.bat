@echo off
setlocal
rem filmify-drop — drag a video file or folder onto this icon to get a fast
rem split-screen preview of the film look (original left, graded right).

if "%~1"=="" (
  echo.
  echo   Drag a video file or folder onto this icon to preview the film look.
  echo.
  pause
  exit /b 1
)

set "SCRIPT=%~dp0filmify.py"
where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py" ) else ( set "PY=python" )

%PY% --version >nul 2>nul
if not %errorlevel%==0 (
  echo.
  echo   Python was not found. Install it from https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" during install, then try again.
  echo.
  pause
  exit /b 1
)

if exist "%~1\" (
  rem Folder: batch a fast split-screen preview of every clip
  %PY% "%SCRIPT%" "%~1" --compare --preview
) else (
  rem Single clip: open the control panel in the browser
  echo.
  echo   Opening the filmify panel in your browser.
  echo   Keep this window open while you work; close it when done.
  echo.
  %PY% "%SCRIPT%" "%~1" --ui
)
echo.
pause
