@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

set "PYW=%HERE%\python\pythonw.exe"
if not exist "%PYW%" (
  echo [ERROR] Portable python not found:
  echo   %PYW%
  echo Make sure the python\ subfolder exists with pythonw.exe in it.
  pause
  exit /b 1
)

REM Build the launcher shim exe (FileDescription = "Markdown Editor"). The Win11
REM Open With picker shows the command exe's description, so pythonw.exe shows up
REM as "Python". Our own exe fixes the name for good. csc.exe ships with Windows.
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if exist "%CSC%" (
  if exist "%HERE%\md-editor.ico" (
    "%CSC%" /nologo /target:winexe /win32icon:"%HERE%\md-editor.ico" /out:"%HERE%\MarkdownEditor.exe" "%HERE%\MarkdownEditor.cs"
  ) else (
    "%CSC%" /nologo /target:winexe /out:"%HERE%\MarkdownEditor.exe" "%HERE%\MarkdownEditor.cs"
  )
) else (
  echo [WARN] csc.exe not found, cannot build MarkdownEditor.exe
)

REM Build the uninstaller GUI (icon = pixel MD with red X badge).
if exist "%CSC%" (
  if exist "%HERE%\uninstall-md.ico" (
    "%CSC%" /nologo /target:winexe /win32icon:"%HERE%\uninstall-md.ico" /out:"%HERE%\UninstallMDEditor.exe" "%HERE%\UninstallMDEditor.cs"
  ) else (
    "%CSC%" /nologo /target:winexe /out:"%HERE%\UninstallMDEditor.exe" "%HERE%\UninstallMDEditor.cs"
  )
) else (
  echo [WARN] csc.exe not found, cannot build UninstallMDEditor.exe
)

echo Install path: %HERE%
echo Python:       %PYW%
echo.

echo [1/5] Register .md context menu (HKCU, no admin needed)...
reg add "HKCU\Software\Classes\.md\shell\MDViewer" /ve /t REG_SZ /d "Open with Markdown Editor" /f
reg add "HKCU\Software\Classes\.md\shell\MDViewer\command" /ve /t REG_SZ /d "%HERE%\MarkdownEditor.exe \"%%1\"" /f

echo [2/5] Set .md default association (double-click opens this editor)...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$k='HKCU:\Software\Classes\.md'; $v=Get-ItemProperty -Path $k -Name '(default)' -ErrorAction SilentlyContinue; if($v){($v.'(default)')}else{''}" > "%HERE%\.mdinstall.bak"
reg add "HKCU\Software\Classes\.md" /ve /t REG_SZ /d "MDViewer.md" /f
reg add "HKCU\Software\Classes\MDViewer.md" /ve /t REG_SZ /d "Markdown Document (MD Editor)" /f
REM Win11 OpenWith picker shows the command exe's FileDescription ("Python") unless
REM FriendlyTypeName exists. Provide it, plus a proper document icon.
reg add "HKCU\Software\Classes\MDViewer.md" /v FriendlyTypeName /t REG_EXPAND_SZ /d "Markdown Editor" /f
reg add "HKCU\Software\Classes\MDViewer.md\DefaultIcon" /ve /t REG_SZ /d "%HERE%\md-editor.ico" /f
reg add "HKCU\Software\Classes\MDViewer.md\shell\open\command" /ve /t REG_SZ /d "%HERE%\MarkdownEditor.exe \"%%1\"" /f
REM Register the shim as an application so the picker lists it with the right name/icon
reg add "HKCU\Software\Classes\Applications\MarkdownEditor.exe\shell\open\command" /ve /t REG_SZ /d "%HERE%\MarkdownEditor.exe \"%%1\"" /f
reg add "HKCU\Software\Classes\Applications\MarkdownEditor.exe\DefaultIcon" /ve /t REG_SZ /d "%HERE%\md-editor.ico" /f
REM Clear stale UserChoice. Plain "reg delete" FAILS here: Windows puts an explicit
REM Deny-SetValue ACE on UserChoice (anti-hijack), so reg.exe cannot even open it writable.
REM Use .NET DeleteSubKey (different code path) and report the result loudly.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "if(Test-Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\UserChoice'){try { [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey('Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\UserChoice'); 'UserChoice cleared' } catch { 'UserChoice delete failed: ' + $_.Exception.Message }} else { 'UserChoice not present (skip)' }"
REM Safety net: the stale UserChoice points to ProgID "Markdown Document" which does NOT
REM exist anywhere. Recreate it here so the association resolves to OUR editor regardless.
reg add "HKCU\Software\Classes\Markdown Document" /ve /t REG_SZ /d "Markdown Editor" /f >nul 2>&1
reg add "HKCU\Software\Classes\Markdown Document" /v FriendlyTypeName /t REG_EXPAND_SZ /d "Markdown Editor" /f >nul 2>&1
reg add "HKCU\Software\Classes\Markdown Document\DefaultIcon" /ve /t REG_SZ /d "%HERE%\md-editor.ico" /f >nul 2>&1
reg add "HKCU\Software\Classes\Markdown Document\shell\open\command" /ve /t REG_SZ /d "%HERE%\MarkdownEditor.exe \"%%1\"" /f >nul 2>&1
REM Remove stale pythonw entry from Open With history (it was MRU-first, shown as "Python")
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\OpenWithList" /v d /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\OpenWithList" /v MRUList /t REG_SZ /d "befgac" /f >nul 2>&1
REM Add this editor into the Open With list
reg add "HKCU\Software\Classes\.md\OpenWithProgids" /v MDViewer.md /t REG_SZ /d "" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\OpenWithProgids" /v MDViewer.md /t REG_SZ /d "" /f >nul 2>&1

REM ---- Self-contained Markdown (.smd) file association ----
reg add "HKCU\Software\Classes\.smd" /ve /t REG_SZ /d "MDViewer.smd" /f
reg add "HKCU\Software\Classes\.smd\shell\MDViewer" /ve /t REG_SZ /d "Open with Markdown Editor" /f
reg add "HKCU\Software\Classes\.smd\shell\MDViewer\command" /ve /t REG_SZ /d "%HERE%\MarkdownEditor.exe \"%%1\"" /f
reg add "HKCU\Software\Classes\MDViewer.smd" /ve /t REG_SZ /d "Self-contained Markdown Document" /f
reg add "HKCU\Software\Classes\MDViewer.smd" /v FriendlyTypeName /t REG_EXPAND_SZ /d "Markdown Editor" /f
reg add "HKCU\Software\Classes\MDViewer.smd\DefaultIcon" /ve /t REG_SZ /d "%HERE%\md-editor.ico" /f
reg add "HKCU\Software\Classes\MDViewer.smd\shell\open\command" /ve /t REG_SZ /d "%HERE%\MarkdownEditor.exe \"%%1\"" /f
reg add "HKCU\Software\Classes\.smd\OpenWithProgids" /v MDViewer.smd /t REG_SZ /d "" /f >nul 2>&1

echo [3/5] Create Desktop / Start Menu shortcuts...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%HERE%\_mklnk.ps1" -Here "%HERE%"

echo [4/5] Windows 11 context menu visibility...
if /i "%~1"=="nolegacy" (
  echo   Legacy menu NOT enabled. The item will appear under "Show more options".
) else (
  reg add "HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32" /ve /t REG_SZ /d "" /f
  echo   Legacy context menu enabled. The item shows directly on right-click.
  echo   Note: this switches all right-click menus to classic style.
  echo   Run uninstall.cmd to revert.
)

echo [5/5] Register "Apps & features" uninstall entry (HKCU)...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor" /v DisplayName /t REG_SZ /d "MDEditor (Markdown Editor)" /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor" /v DisplayIcon /t REG_SZ /d "%HERE%\md-editor.ico" /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor" /v UninstallString /t REG_SZ /d "\"%HERE%\UninstallMDEditor.exe\"" /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor" /v NoModify /t REG_DWORD /d 1 /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor" /v NoRepair /t REG_DWORD /d 1 /f

echo.
echo Done. Right-click any .md file, or just double-click it.
echo Tray icon lives in the notification area: new blank doc / exit.
echo Uninstall: Settings - Apps - "MDEditor (Markdown Editor)".
REM pause hangs forever when install.cmd is invoked silently by the setup
REM exe (no interactive console). The setup passes "nopause" to skip it.
if /i not "%~1"=="nopause" pause
endlocal
