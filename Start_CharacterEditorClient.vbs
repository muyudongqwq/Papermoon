Option Explicit

Dim shell, files, command, argument
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
shell.CurrentDirectory = files.GetParentFolderName(WScript.ScriptFullName)
If Not files.FileExists(files.BuildPath(shell.CurrentDirectory, "CharacterEditorClient\__main__.py")) Then
    MsgBox "CharacterEditorClient was not found in this folder.", vbCritical, "Papermoon"
    WScript.Quit 1
End If
command = "pyw.exe -3 -m CharacterEditorClient"
For Each argument In WScript.Arguments
    command = command & " " & Chr(34) & argument & Chr(34)
Next
On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    MsgBox "Cannot start CharacterEditorClient. Please check your Python installation." & vbCrLf & Err.Description, vbCritical, "Papermoon"
    WScript.Quit 1
End If
