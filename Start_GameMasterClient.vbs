Option Explicit
Dim shell, fso, root, pythonw, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "Papermoon virtual environment was not found.", vbCritical, "Papermoon GM Client"
    WScript.Quit 1
End If
command = Chr(34) & pythonw & Chr(34) & " -m GameMasterClient"
shell.CurrentDirectory = root
shell.Run command, 1, False

