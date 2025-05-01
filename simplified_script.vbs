Option Explicit

' Enhanced script to run the batch file with error handling
Dim shell, fso, scriptPath, batchFile, returnValue

' Create file system and shell objects
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get the path to the script folder
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName)

' Full path to the batch file
batchFile = scriptPath & "\simplified_bank_statements.bat"

' Check if the batch file exists
If Not fso.FileExists(batchFile) Then
    MsgBox "Error: Batch file not found at:" & vbCrLf & batchFile, vbCritical, "Bank Statement Processor"
    WScript.Quit(1)
End If

' Run the batch file with error handling
On Error Resume Next
returnValue = shell.Run("cmd /c """ & batchFile & """", 1, True)

If Err.Number <> 0 Then
    MsgBox "Error executing batch file: " & Err.Description, vbCritical, "Bank Statement Processor"
    WScript.Quit(2)
End If

' Optional: Add return value checking
If returnValue <> 0 Then
    MsgBox "Batch file completed with return code: " & returnValue, vbInformation, "Bank Statement Processor"
End If 