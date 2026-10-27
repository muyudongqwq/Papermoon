Option Explicit

Dim shell, files, root, python, command, argument
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
python = files.BuildPath(root, ".venv\Scripts\pythonw.exe")

If files.FileExists(python) Then
    command = Chr(34) & python & Chr(34) & " -m MapEditorClient"
Else
    command = "pyw.exe -3 -m MapEditorClient"
End If

For Each argument In WScript.Arguments
    command = command & " " & Chr(34) & argument & Chr(34)
Next

On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    MsgBox "Cannot start MapEditorClient. Please install requirements-qt.txt." & vbCrLf & Err.Description, vbCritical, "Papermoon"
    WScript.Quit 1
End If

