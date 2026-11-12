Option Explicit
Dim shell, fso, root, pythonw, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "没有找到Papermoon虚拟环境中的pythonw.exe。", vbCritical, "Papermoon GM终端"
    WScript.Quit 1
End If
command = """" & pythonw & """ -m GameMasterClient"
shell.CurrentDirectory = root
shell.Run command, 1, False

