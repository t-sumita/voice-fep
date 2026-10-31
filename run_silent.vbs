' run_silent.vbs
' voice-fep をコンソールウィンドウなしでバックグラウンド起動する。
' タスクスケジューラや「スタートアップ」フォルダに登録して使用。
'
' 使い方:
'   wscript run_silent.vbs
'   (またはファイルをダブルクリック)

Option Explicit

Dim FSO, WshShell, ScriptDir, PythonW, MainPy

Set FSO     = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
PythonW   = ScriptDir & "\.venv\Scripts\pythonw.exe"
MainPy    = ScriptDir & "\main.py"

' .venv の pythonw が存在すればそれを優先、なければ PATH 上の pythonw を使用
If FSO.FileExists(PythonW) Then
    WshShell.Run """" & PythonW & """ """ & MainPy & """", 0, False
Else
    WshShell.Run "pythonw """ & MainPy & """", 0, False
End If

Set FSO      = Nothing
Set WshShell = Nothing
