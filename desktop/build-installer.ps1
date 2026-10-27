param([string]$AppVersion = '1.0.0')
$ErrorActionPreference = 'Stop'
if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'AppVersion must be numeric: major.minor.build.' }
if (-not (Test-Path "$PSScriptRoot/dist/ZaloFlow/ZaloFlow.exe")) { throw 'Run build-windows.ps1 first.' }
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$compilerPath = if ($compiler) { $compiler.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe' }
if (-not (Test-Path $compilerPath)) { throw 'Install Inno Setup 6 before building the installer.' }
& $compilerPath "/DAppVersion=$AppVersion" "$PSScriptRoot/installer.iss"
if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed.' }
$setup = Join-Path $PSScriptRoot 'dist/installer/ZaloFlow-Setup-x64.exe'
if (-not (Test-Path $setup)) { throw 'Missing Windows installer.' }
$digest = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$digest  ZaloFlow-Setup-x64.exe" | Set-Content "$setup.sha256" -Encoding ascii
Write-Host "Ready: $setup"
