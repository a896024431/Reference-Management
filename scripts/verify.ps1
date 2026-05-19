$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    python .\scripts\vault\refresh_indexes.py --vault-root . --check
    python -m unittest discover -s .\scripts\tests

    $validator = Join-Path $env:USERPROFILE ".codex\skills\.system\skill-creator\scripts\quick_validate.py"
    python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('yaml') else 1)"
    if ((Test-Path -LiteralPath $validator) -and ($LASTEXITCODE -eq 0)) {
        python $validator .\skills\zotero-collection-manager
        python $validator .\skills\zotero-data-fetcher
        python $validator .\skills\zotero-analytical-writer
        python $validator .\skills\research-vault-literature-retrieval
    } elseif (Test-Path -LiteralPath $validator) {
        Write-Host "Skipping skill-creator quick_validate.py because PyYAML is not installed in this Python environment."
    }
} finally {
    Pop-Location
}
