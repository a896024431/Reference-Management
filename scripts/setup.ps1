param(
    [string]$ZoteroDataDir = "",
    [string]$VaultRoot = ".",
    [string]$NotesDir = "note"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$localDir = Join-Path $repoRoot ".local"
$configPath = Join-Path $localDir "config.toml"

New-Item -ItemType Directory -Force -Path $localDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot $NotesDir) | Out-Null

if (-not $ZoteroDataDir) {
    $candidate = Join-Path $env:USERPROFILE "Zotero"
    if (Test-Path -LiteralPath (Join-Path $candidate "zotero.sqlite")) {
        $ZoteroDataDir = $candidate
    }
}

if (Test-Path -LiteralPath $configPath) {
    Write-Host "Config already exists: $configPath"
    Write-Host "Edit it manually if this computer uses a different Zotero data directory."
    exit 0
}

$vaultFullPath = (Resolve-Path -LiteralPath (Join-Path $repoRoot $VaultRoot)).Path.Replace("\", "\\")
$zoteroEscaped = $ZoteroDataDir.Replace("\", "\\")
$notesEscaped = $NotesDir.Replace("\", "\\")

$content = @"
[zotero]
data_dir = "$zoteroEscaped"
library_id = "library"

[vault]
root = "$vaultFullPath"
notes_dir = "$notesEscaped"

[processing]
raw_dir = ".local/raw"
"@

Set-Content -LiteralPath $configPath -Value $content -Encoding UTF8

Write-Host "Created local config: $configPath"
Write-Host "This file is ignored by Git and should be configured separately on each computer."
