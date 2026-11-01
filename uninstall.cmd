@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

REM SAFETY (2026-10-19 incident): this script NEVER deletes program files.
REM It only clears system integration (registry / shortcuts / ARP entry).
REM File deletion is opt-in, double-confirmed, and lives in the uninstaller
REM GUI (UninstallMDWright.exe), never in this script.

echo [1/6] Remove .md/.smd context menu and associations...
reg delete "HKCU\Software\Classes\.md\shell\MDWright" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.md\OpenWithProgids" /v MDWright.md /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\OpenWithProgids" /v MDWright.md /f >nul 2>&1
reg delete "HKCU\Software\Classes\MDWright.md" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.smd\shell\MDWright" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.smd\OpenWithProgids" /v MDWright.smd /f >nul 2>&1
reg delete "HKCU\Software\Classes\MDWright.smd" /f >nul 2>&1
reg delete "HKCU\Software\Classes\Applications\MDWright.exe" /f >nul 2>&1
reg delete "HKCU\Software\Classes\Markdown Document" /f >nul 2>&1

echo [2/6] Restore .md/.smd default associations...
REM Only restore the backup when the default still points at us. If the user
REM picked another editor after installing, their newer choice wins.
set "__MDWHERE=%HERE%"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$sub='Software\Classes\.md'; $k='HKCU:\'+$sub; $bak=Join-Path $env:__MDWHERE '.mdinstall.bak'; $old=''; if(Test-Path $bak){ $old=((Get-Content $bak -Raw -ErrorAction SilentlyContinue)+'').Trim() }; $cur=((Get-ItemProperty -Path $k -Name '(default)' -ErrorAction SilentlyContinue).'(default)'+''); if($cur -ne 'MDWright.md'){ Write-Host '  .md default changed by user after install; left as is.' } elseif($old -and $old -ne 'MDWright.md'){ Set-ItemProperty -Path $k -Name '(default)' -Value $old; Write-Host '  .md default restored.' } else { $rk=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($sub,$true); if($rk){ try { $rk.DeleteValue('') } catch {}; $rk.Close() }; Write-Host '  .md default cleared.' }"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$sub='Software\Classes\.smd'; $k='HKCU:\'+$sub; $bak=Join-Path $env:__MDWHERE '.smdinstall.bak'; $old=''; if(Test-Path $bak){ $old=((Get-Content $bak -Raw -ErrorAction SilentlyContinue)+'').Trim() }; $cur=((Get-ItemProperty -Path $k -Name '(default)' -ErrorAction SilentlyContinue).'(default)'+''); if($cur -ne 'MDWright.smd'){ Write-Host '  .smd default changed by user after install; left as is.' } elseif($old -and $old -ne 'MDWright.smd'){ Set-ItemProperty -Path $k -Name '(default)' -Value $old; Write-Host '  .smd default restored.' } else { $rk=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($sub,$true); if($rk){ try { $rk.DeleteValue('') } catch {}; $rk.Close() }; Write-Host '  .smd default cleared.' }"
del /f /q "%HERE%\.mdinstall.bak" >nul 2>&1
del /f /q "%HERE%\.smdinstall.bak" >nul 2>&1

echo [3/6] Remove Desktop / Start Menu shortcuts...
del /f /q "%USERPROFILE%\Desktop\MDWright.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\MDWright.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Uninstall MDWright.lnk" >nul 2>&1

echo [4/6] Restore Windows 11 default context menu...
REM Only revert the classic menu if THIS install enabled it (marker written by
REM "install.cmd legacy"). A user who had classic menus before installing keeps
REM their own setting after uninstall.
if exist "%HERE%\.legacy.menu" (
  reg delete "HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}" /f >nul 2>&1
  del /f /q "%HERE%\.legacy.menu" >nul 2>&1
  echo   Classic context menu reverted (this install had enabled it).
) else (
  echo   Classic context menu was not enabled by this install; left as is.
)

echo [5/6] Stop running md_server backend...
REM Match the process image too: a bare command-line substring match would
REM also kill editors / shells that merely mention md_server.py in their args.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and ($_.CommandLine -like '*md_server.py*' -or $_.CommandLine -like '*_md_run.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [6/6] Remove "Apps & features" uninstall entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDWright" /f >nul 2>&1

echo.
echo Uninstall complete. Program files were NOT deleted:
echo   %HERE%
echo Delete that folder manually if you no longer need it.
if /i not "%~1"=="nopause" pause
endlocal
