Set fso = CreateObject("Scripting.FileSystemObject")
target = fso.GetParentFolderName(WScript.ScriptFullName) & "\afrobot_service.cmd"
CreateObject("WScript.Shell").Run """" & target & """", 0, False
