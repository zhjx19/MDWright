@echo off
REM Stop the running MD editor backend (safe even if it is not running).
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*md_server.py*' -or $_.CommandLine -like '*_md_run.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Stop signal sent. (No effect if backend is not running.)
