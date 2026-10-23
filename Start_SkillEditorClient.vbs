Option Explicit

Dim shell, files, command, argument
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
shell.CurrentDirectory = files.GetParentFolderName(WScript.ScriptFullName)

command = "pyw.exe -3 -m SkillEditorClient.executable"
For Each argument In WScript.Arguments
    command = command & " " & Chr(34) & argument & Chr(34)
Next

On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    MsgBox "Cannot start SkillEditorClient. Please check your Python installation." & vbCrLf & Err.Description, vbCritical, "Papermoon"
    WScript.Quit 1
End If
