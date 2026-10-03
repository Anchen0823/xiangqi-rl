param([string]$Name='弈境')
$ErrorActionPreference='Stop'
$repoRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$package=Get-Content -LiteralPath (Join-Path $repoRoot 'dist/desktop/latest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $package.executable -PathType Leaf)) { throw 'Packaged application is missing' }
$desktopDirectory=[Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktopDirectory) { throw 'Desktop directory unavailable' }
$shortcutPath=Join-Path $desktopDirectory ($Name + '.lnk')
$shell=New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
  $existing=$shell.CreateShortcut($shortcutPath)
  if (-not $existing.TargetPath.StartsWith($repoRoot,[StringComparison]::OrdinalIgnoreCase)) {
    throw "A different application's shortcut already uses this name: $shortcutPath"
  }
}
$shortcut=$shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath=$package.executable
$shortcut.WorkingDirectory=$package.directory
$shortcut.IconLocation=$package.executable + ',0'
$shortcut.Description='弈境 · 普通象棋、变体实验室、揭棋与翻棋'
$shortcut.Save()
$verified=$shell.CreateShortcut($shortcutPath)
if ($verified.TargetPath -ne $package.executable) { throw 'Shortcut target verification failed' }
[pscustomobject]@{Shortcut=$shortcutPath;Target=$verified.TargetPath;WorkingDirectory=$verified.WorkingDirectory} | ConvertTo-Json
