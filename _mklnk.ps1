param([string]$Here)
$WScript = New-Object -ComObject WScript.Shell
$exe = Join-Path $Here 'MarkdownEditor.exe'
$ico = Join-Path $Here 'md-editor.ico'

$desktop = [Environment]::GetFolderPath('Desktop')
$s = $WScript.CreateShortcut((Join-Path $desktop 'Markdown Editor.lnk'))
$s.TargetPath = $exe
$s.WorkingDirectory = $Here
$s.IconLocation = $ico
$s.Description = 'Markdown Editor (AI-assisted)'
$s.Save()

$start = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$s2 = $WScript.CreateShortcut((Join-Path $start 'Markdown Editor.lnk'))
$s2.TargetPath = $exe
$s2.WorkingDirectory = $Here
$s2.IconLocation = $ico
$s2.Description = 'Markdown Editor (AI-assisted)'
$s2.Save()

$uexe = Join-Path $Here 'UninstallMDEditor.exe'
$uico = Join-Path $Here 'uninstall-md.ico'
if (Test-Path $uexe) {
  $s3 = $WScript.CreateShortcut((Join-Path $start 'Uninstall MDEditor.lnk'))
  $s3.TargetPath = $uexe
  $s3.WorkingDirectory = $Here
  $s3.IconLocation = $uico
  $s3.Description = 'Uninstall MDEditor'
  $s3.Save()
}

Write-Host 'shortcuts created'
