' filmify-quiet.vbs — launches the filmify panel with no console window at all.
' The shortcut made by "Make filmify app.bat" points here, so double-clicking
' the filmify icon opens straight to the panel (or, on first run, the silent
' setup) with nothing flashing on screen.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
' Run the setup/launch batch fully hidden (0), don't wait (False).
' START-HERE-WINDOWS.bat handles Python/FFmpeg setup, then opens the panel.
sh.Run "cmd /c """"" & here & "\START-HERE-WINDOWS.bat"" --quiet""", 0, False
