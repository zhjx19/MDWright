@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

REM SAFETY (2026-10-19 incident): this script NEVER deletes program files.
REM It only clears system integration (registry / shortcuts / ARP entry).
REM File deletion is opt-in, double-confirmed, and lives in the uninstaller
REM GUI (UninstallMDEditor.exe), never in this script.

echo [1/6] Remove .md/.smd context menu and associations...
reg delete "HKCU\Software\Classes\.md\shell\MDViewer" /f >nul 2>&1
reg delete "HKCU\Software\Classes\MDViewer.md" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.smd" /f >nul 2>&1
reg delete "HKCU\Software\Classes\MDViewer.smd" /f >nul 2>&1
reg delete "HKCU\Software\Classes\Applications\MarkdownEditor.exe" /f >nul 2>&1
reg delete "HKCU\Software\Classes\Markdown Document" /f >nul 2>&1

echo [2/6] Restore .md default association...
if exist "%HERE%\.mdinstall.bak" (
  set /p OLDVAL=<"%HERE%\.mdinstall.bak"
  if defined OLDVAL (
    if not "%OLDVAL%"=="" reg add "HKCU\Software\Classes\.md" /ve /t REG_SZ /d "%OLDVAL%" /f >nul
  ) else (
    reg delete "HKCU\Software\Classes\.md" /ve /f >nul 2>&1
  )
) else (
  reg delete "HKCU\Software\Classes\.md" /ve /f >nul 2>&1
)
del /f /q "%HERE%\.mdinstall.bak" >nul 2>&1

echo [3/6] Remove Desktop / Start Menu shortcuts...
del /f /q "%USERPROFILE%\Desktop\Markdown Editor.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Markdown Editor.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Uninstall MDEditor.lnk" >nul 2>&1

echo [4/6] Restore Windows 11 default context menu...
reg delete "HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}" /f >nul 2>&1

echo [5/6] Stop running md_server backend...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*md_server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [6/6] Remove "Apps & features" uninstall entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor" /f >nul 2>&1

echo.
echo Uninstall complete. Program files were NOT deleted:
echo   %HERE%
echo Delete that folder manually if you no longer need it.
if /i not "%~1"=="nopause" pause
endlocal
