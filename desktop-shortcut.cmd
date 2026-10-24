@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

if not exist "%HERE%\MDWright.exe" (
  echo [ERROR] MDWright.exe not found next to this script.
  pause
  exit /b 1
)

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell;$desktop=[Environment]::GetFolderPath('Desktop');$lnk=$ws.CreateShortcut((Join-Path $desktop 'MDWright.lnk'));$lnk.TargetPath='%HERE%\MDWright.exe';$lnk.WorkingDirectory='%HERE%';$lnk.IconLocation='%HERE%\mdwright.ico';$lnk.Description='MDWright (AI-assisted)';$lnk.Save();Write-Host 'Desktop shortcut created.'"

echo Done. Look for "MDWright" on your desktop.
pause
