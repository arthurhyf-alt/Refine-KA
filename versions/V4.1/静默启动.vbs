Option Explicit

Dim shell, fso, folder, localAppData, pythonw, bundled, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

folder = fso.GetParentFolderName(WScript.ScriptFullName)
localAppData = shell.ExpandEnvironmentStrings("%LocalAppData%")
pythonw = localAppData & "\Programs\Python\Python312\pythonw.exe"

If Not fso.FileExists(pythonw) Then
  pythonw = localAppData & "\Programs\Python\Python313\pythonw.exe"
End If

If Not fso.FileExists(pythonw) Then
  bundled = "C:\Users\arthu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
  pythonw = bundled
End If

If Not fso.FileExists(pythonw) Then
  MsgBox "Python runtime was not found. Run the Python installer helper first.", 16, "Industry Screener"
  WScript.Quit 1
End If

command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & folder & "\app.py" & Chr(34)
shell.CurrentDirectory = folder
shell.Run command, 0, False
