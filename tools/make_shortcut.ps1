# Creates (or refreshes) a desktop shortcut that launches Recall & Reflect
# with the app icon. Run once from the repo:
#
#     powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
#
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $desktop 'Recall & Reflect.lnk'))
$lnk.TargetPath = Join-Path $root 'run.bat'
$lnk.WorkingDirectory = $root
$lnk.IconLocation = (Join-Path $root 'app.ico') + ',0'
$lnk.Description = 'Recall & Reflect - local spaced repetition'
$lnk.WindowStyle = 7   # start the server console minimized
$lnk.Save()
Write-Host "Done - 'Recall & Reflect' is on your Desktop."
