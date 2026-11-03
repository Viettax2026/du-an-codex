param([string]$AppVersion = '1.0.0', [switch]$Local)
$ErrorActionPreference = 'Stop'
if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'AppVersion must be numeric: major.minor.build.' }
$product = if ($Local) { 'ZaloFlowLocal' } else { 'ZaloFlow' }
if (-not (Test-Path "$PSScriptRoot/dist/$product/ZaloFlow.exe")) { throw 'Build the selected Windows edition first.' }
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$compilerPath = if ($compiler) { $compiler.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe' }
if (-not (Test-Path $compilerPath)) { throw 'Install Inno Setup 6 before building the installer.' }
$definition = if ($Local) { 'local.iss' } else { 'installer.iss' }
& $compilerPath "/DAppVersion=$AppVersion" "$PSScriptRoot/$definition"
if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed.' }
$relativeSetup = if ($Local) { 'dist/local-installer/ZaloFlow-Local-Setup-x64.exe' } else { 'dist/installer/ZaloFlow-Setup-x64.exe' }
$setup = Join-Path $PSScriptRoot $relativeSetup
if (-not (Test-Path $setup)) { throw 'Missing Windows installer.' }
$digest = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$digest  $([IO.Path]::GetFileName($setup))" | Set-Content "$setup.sha256" -Encoding ascii
Write-Host "Ready: $setup"
