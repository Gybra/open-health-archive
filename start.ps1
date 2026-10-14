# Start Open Health Archive on Windows: import the newest Health Connect export from
# the chosen folder, then open the viewer. Mirrors start.sh; run with -Choose to pick
# the folders again. Everything except the folder dialogs runs in Docker.
# Usage: powershell -ExecutionPolicy Bypass -File start.ps1 [-Choose]
param([switch]$Choose)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$ConfigDir = if ($env:HEALTHVIZ_CONFIG_DIR) { $env:HEALTHVIZ_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.config\healthviz' }
$Prefs = Join-Path $ConfigDir 'launcher.conf'
$Url = 'http://127.0.0.1:8501'

function Stop-Launcher([string]$Message) {
    [Console]::Error.WriteLine($Message)
    exit 1
}

# Read one saved preference; the file is parsed, never executed.
function Get-Pref([string]$Key) {
    if (-not (Test-Path -LiteralPath $Prefs)) { return $null }
    foreach ($line in [IO.File]::ReadAllLines($Prefs)) {
        if ($line.StartsWith("$Key=")) { return $line.Substring($Key.Length + 1) }
    }
    return $null
}

function Select-Folder([string]$Prompt) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Prompt
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $dialog.SelectedPath }
    return $null
}

function Get-Folder([string]$Key, [string]$Prompt) {
    $value = Get-Pref $Key
    if ($Choose -or -not $value -or -not (Test-Path -LiteralPath $value -PathType Container)) {
        $value = Select-Folder $Prompt
    }
    if (-not $value -or -not (Test-Path -LiteralPath $value -PathType Container)) {
        Stop-Launcher 'No folder chosen; nothing was started.'
    }
    return $value
}

# Returns only the exit code; Docker's own output goes straight to the console.
function Invoke-Compose {
    & docker compose -f compose.yaml -f compose.launcher.yaml @args | Out-Host
    return $LASTEXITCODE
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Launcher 'Docker is required: install and start Docker Desktop.'
}
$archive = Get-Folder 'archive_dir' 'Choose the archive folder'
$imports = Get-Folder 'import_dir' 'Choose the folder where you download Health Connect exports'
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
[IO.File]::WriteAllLines($Prefs, [string[]]@("archive_dir=$archive", "import_dir=$imports"))
$cache = if ($env:HEALTHVIZ_CACHE_DIR) { $env:HEALTHVIZ_CACHE_DIR } else { Join-Path $env:LOCALAPPDATA 'OpenHealthArchive\viewer' }
$cacheParent = Split-Path -Parent $cache
if (-not (Test-Path -LiteralPath $cacheParent -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $cacheParent | Out-Null
}

$label = $imports
if ($imports.StartsWith($env:USERPROFILE + '\')) { $label = '~' + $imports.Substring($env:USERPROFILE.Length) }
$env:HEALTHVIZ_ARCHIVE_DIR = $archive
$env:HEALTHVIZ_IMPORT_DIR = $imports
$env:HEALTHVIZ_IMPORT_LABEL = $label
$env:HEALTHVIZ_CONFIG_DIR = $ConfigDir
$env:HEALTHVIZ_CACHE_DIR = $cache

# Rebuild so an updated checkout is what runs; without network keep the existing image.
if ((Invoke-Compose build viewer) -ne 0) {
    & docker image inspect open-health-archive-viewer *> $null
    if ($LASTEXITCODE -ne 0) { Stop-Launcher 'Could not build the viewer image; connect to the internet once and retry.' }
    [Console]::Error.WriteLine('Could not rebuild; using the existing image.')
}
# The viewer's own identity creates the cache, so the read model sees it as its own.
if (-not (Test-Path -LiteralPath $cache -PathType Container)) {
    & docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true `
        --mount "type=bind,src=$cacheParent,dst=/cache-parent" open-health-archive-viewer `
        python -c "import os, sys; os.mkdir('/cache-parent/' + sys.argv[1], 0o700)" (Split-Path -Leaf $cache) | Out-Host  # no inner double quotes: PowerShell 5 drops them
    if ($LASTEXITCODE -ne 0) { Stop-Launcher 'Could not create the private cache folder.' }
}
Invoke-Compose stop viewer | Out-Null  # nothing to stop on first run
if ((Invoke-Compose run --rm import) -ne 0) {
    [Console]::Error.WriteLine('Import failed; the viewer shows the reason.')
}
if ((Invoke-Compose up -d viewer) -ne 0) { Stop-Launcher 'The viewer did not start.' }

for ($try = 0; $try -lt 60; $try++) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "$Url/_stcore/health" | Out-Null
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
Start-Process $Url
Write-Output "Open Health Archive: $Url"
