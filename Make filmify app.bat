@echo off
setlocal
rem Make filmify app — run me ONCE. I create a "filmify" shortcut with the
rem app icon on your Desktop and in your Start menu, so from now on you just
rem click the filmify icon like any other program. No console, no typing.
rem
rem (Windows may show "Windows protected your PC" the first time you run a
rem downloaded file. That's SmartScreen being cautious — click "More info"
rem then "Run anyway". It only happens once.)

set "HERE=%~dp0"
set "TARGET=%HERE%filmify-quiet.vbs"
set "ICON=%HERE%filmify.ico"

echo.
echo   Creating the filmify shortcut...

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$start = [Environment]::GetFolderPath('Programs');" ^
  "foreach ($dir in @($desktop, $start)) {" ^
  "  $lnk = $ws.CreateShortcut((Join-Path $dir 'filmify.lnk'));" ^
  "  $lnk.TargetPath = '%TARGET%';" ^
  "  $lnk.WorkingDirectory = '%HERE%';" ^
  "  $lnk.IconLocation = '%ICON%';" ^
  "  $lnk.Description = 'filmify - the feel of film';" ^
  "  $lnk.Save();" ^
  "}"

if %errorlevel%==0 (
  echo.
  echo   Done. There is now a "filmify" icon on your Desktop and in your
  echo   Start menu. Click it any time to open filmify -- pin it to your
  echo   taskbar if you like. You can keep this folder wherever it is;
  echo   just don't move it, since the shortcut points here.
) else (
  echo.
  echo   Couldn't create the shortcut automatically. You can still use
  echo   filmify by double-clicking START-HERE-WINDOWS.bat.
)
echo.
pause
