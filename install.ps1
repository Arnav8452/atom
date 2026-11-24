<#
.SYNOPSIS
Install, update, or uninstall Atom for the Antigravity app on Windows.

.EXAMPLE
  .\install.ps1
  .\install.ps1 -Uninstall
#>
param(
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$PluginDir = Join-Path $env:USERPROFILE ".gemini\config\plugins\atom"
$StartMenuShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Antigravity (Atom).lnk"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Antigravity (Atom).lnk"

function Say([string]$Msg) {
  Write-Host "[atom] $Msg"
}

if ($Uninstall) {
  if (Test-Path $PluginDir) {
    Remove-Item -Recurse -Force $PluginDir
    Say "removed $PluginDir"
  }
  foreach ($lnk in @($StartMenuShortcut, $DesktopShortcut)) {
    if (Test-Path $lnk) {
      Remove-Item -Force $lnk
      Say "removed $lnk"
    }
  }
  Say "done. Restart Antigravity to finish. State in $env:USERPROFILE\.antigravity-atom can be deleted."
  exit 0
}

# Locate checkout, or clone/update one when piped via `irm ... | iex`.
$ScriptPath = $MyInvocation.MyCommand.Path
$Root = if ($PSScriptRoot) { $PSScriptRoot } elseif ($ScriptPath) { Split-Path -Parent $ScriptPath } else { "" }
if (-not $Root -or -not (Test-Path (Join-Path $Root "plugin.json"))) {
  $Repo = if ($env:ATOM_REPO) { $env:ATOM_REPO } else { "https://github.com/Arnav8452/atom.git" }
  $Root = if ($env:ATOM_DIR) { $env:ATOM_DIR } else { Join-Path $env:LOCALAPPDATA "antigravity-atom" }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required for remote install (or download a release zip and run .\install.ps1)."
  }
  if (Test-Path (Join-Path $Root ".git")) {
    & git -C $Root pull --ff-only --quiet
  } else {
    & git clone --depth 1 $Repo $Root
  }
}
Say "code: $Root"

# Detect Python 3 command for hooks & launcher
$HookPy = $null
$PyExe = $null
$PywExe = $null

$cmdPy = Get-Command py -ErrorAction SilentlyContinue
if ($cmdPy) {
  $HookPy = "py -3"
  $PyExe = (& py -3 -c "import sys; print(sys.executable)" 2>$null).Trim()
} else {
  $cmdPython = Get-Command python -ErrorAction SilentlyContinue
  if ($cmdPython) {
    $HookPy = "python"
    $PyExe = $cmdPython.Source
  }
}

if (-not $PyExe) {
  throw "Python 3 is required on PATH (or via the 'py' launcher)."
}
$candidatePyw = Join-Path (Split-Path -Parent $PyExe) "pythonw.exe"
if (Test-Path $candidatePyw) { $PywExe = $candidatePyw } else { $PywExe = $PyExe }

# 1. Copy plugin files into ~/.gemini/config/plugins/atom (avoids Windows symlink privilege issues)
New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
Copy-Item -Force (Join-Path $Root "plugin.json") $PluginDir
Copy-Item -Force (Join-Path $Root "atom_hook.py") $PluginDir

$hooksRaw = Get-Content -Raw (Join-Path $Root "hooks.json")
$hooksPatched = $hooksRaw -replace "python3 -S -I \./atom_hook\.py", "$HookPy -S -I ./atom_hook.py"
Set-Content -Path (Join-Path $PluginDir "hooks.json") -Value $hooksPatched -Encoding UTF8
Say "plugin: $PluginDir (hook command: $HookPy -S -I ./atom_hook.py)"

# 2. Create Start Menu and Desktop shortcuts launching pythonw.exe atom_launch.py
$Launcher = Join-Path $Root "atom_launch.py"
$WshShell = New-Object -ComObject WScript.Shell

$IconPath = $null
foreach ($candidate in @(
  (Join-Path $env:LOCALAPPDATA "Programs\Antigravity\Antigravity.exe"),
  (Join-Path $env:LOCALAPPDATA "Antigravity\Antigravity.exe"),
  (Join-Path $env:ProgramFiles "Antigravity\Antigravity.exe")
)) {
  if (Test-Path $candidate) { $IconPath = "$candidate,0"; break }
}

foreach ($lnkPath in @($StartMenuShortcut, $DesktopShortcut)) {
  $lnkDir = Split-Path -Parent $lnkPath
  if (-not (Test-Path $lnkDir)) { New-Item -ItemType Directory -Force -Path $lnkDir | Out-Null }
  $sc = $WshShell.CreateShortcut($lnkPath)
  $sc.TargetPath = $PywExe
  $sc.Arguments = "`"$Launcher`""
  $sc.WorkingDirectory = $Root
  $sc.Description = "Antigravity - Agentic Desktop Application (with Atom)"
  if ($IconPath) { $sc.IconLocation = $IconPath }
  $sc.Save()
  Say "shortcut: $lnkPath"
}

Say "done. Quit Antigravity and start 'Antigravity (Atom)' from your Start Menu or Desktop."
