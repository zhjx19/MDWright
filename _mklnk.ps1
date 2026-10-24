param([string]$Here)
$WScript = New-Object -ComObject WScript.Shell
$exe = Join-Path $Here 'MDWright.exe'
$ico = Join-Path $Here 'mdwright.ico'

$desktop = [Environment]::GetFolderPath('Desktop')
$s = $WScript.CreateShortcut((Join-Path $desktop 'MDWright.lnk'))
$s.TargetPath = $exe
$s.WorkingDirectory = $Here
$s.IconLocation = $ico
$s.Description = 'MDWright (AI-assisted)'
$s.Save()

$start = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$s2 = $WScript.CreateShortcut((Join-Path $start 'MDWright.lnk'))
$s2.TargetPath = $exe
$s2.WorkingDirectory = $Here
$s2.IconLocation = $ico
$s2.Description = 'MDWright (AI-assisted)'
$s2.Save()

$uexe = Join-Path $Here 'UninstallMDWright.exe'
$uico = Join-Path $Here 'uninstall-mdwright.ico'
if (Test-Path $uexe) {
  $s3 = $WScript.CreateShortcut((Join-Path $start 'Uninstall MDWright.lnk'))
  $s3.TargetPath = $uexe
  $s3.WorkingDirectory = $Here
  $s3.IconLocation = $uico
  $s3.Description = 'Uninstall MDWright'
  $s3.Save()
}

Write-Host 'shortcuts created'
