$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Build on Windows x64.' }
    python -m pip install -r desktop/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed.' }
    Push-Location connector
    try {
        npm.cmd ci --omit=dev
        if ($LASTEXITCODE -ne 0) { throw 'Zalo connector dependencies failed.' }
    } finally { Pop-Location }
    python -m PyInstaller --noconfirm --clean --distpath desktop/dist --workpath desktop/build desktop/zaloflow.spec
    if ($LASTEXITCODE -ne 0) { throw 'Windows package build failed.' }
    Copy-Item desktop/HUONG-DAN.txt desktop/dist/ZaloFlow/HUONG-DAN.txt
    Write-Host 'Ready: desktop/dist/ZaloFlow/ZaloFlow.exe'
} finally { Pop-Location }
