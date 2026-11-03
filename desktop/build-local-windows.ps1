$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Build on Windows x64.' }
    python -m pip install -r desktop/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed.' }
    Push-Location connector
    try {
        npm.cmd ci --omit=dev --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Connector dependencies failed.' }
    } finally { Pop-Location }
    python -m PyInstaller --noconfirm --clean --distpath desktop/dist --workpath desktop/build-local desktop/zaloflow-local.spec
    if ($LASTEXITCODE -ne 0) { throw 'Local Windows package build failed.' }
    Copy-Item desktop/HUONG-DAN-LOCAL.txt desktop/dist/ZaloFlowLocal/HUONG-DAN.txt
    python -m desktop.privacy_audit --strict --app-dir desktop/dist/ZaloFlowLocal --report desktop/dist/local-privacy-audit.json
    if ($LASTEXITCODE -ne 0) { throw 'Local edition privacy audit failed.' }
    Write-Host 'Ready: desktop/dist/ZaloFlowLocal/ZaloFlow.exe'
} finally { Pop-Location }
