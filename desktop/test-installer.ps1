# Run only on the disposable Windows CI runner. No live Zalo operations.
$ErrorActionPreference = 'Stop'
$setup = Join-Path $PSScriptRoot 'dist/installer/ZaloFlow-Setup-x64.exe'
$appPath = Join-Path $env:RUNNER_TEMP 'ZaloFlow installed smoke test'
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'ZaloFlow.lnk'
$startShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'ZaloFlow.lnk'
$dataPath = Join-Path $env:LOCALAPPDATA 'ZaloFlow'
if (-not $env:CI -or -not $env:RUNNER_TEMP) { throw 'Use a disposable Windows CI runner.' }
if (Test-Path $dataPath) { throw 'Do not run installer tests with existing user data.' }

function Run-Installer([string]$exe, [string[]]$installerArgs, [string]$logName) {
    $logPath = Join-Path $env:RUNNER_TEMP $logName
    $process = Start-Process $exe -ArgumentList ($installerArgs + "/LOG=`"$logPath`"") -PassThru
    if (-not $process.WaitForExit(180000)) { Stop-Process -Id $process.Id -Force; throw 'Installer timed out.' }
    if ($process.ExitCode -ne 0) {
        if (Test-Path $logPath) { Get-Content $logPath }
        throw "Installer exited with code $($process.ExitCode)."
    }
}

function Assert-Shortcuts {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in @($desktopShortcut, $startShortcut)) {
        if (-not (Test-Path $path)) { throw "Missing shortcut: $path" }
        $shortcut = $shell.CreateShortcut($path)
        if ($shortcut.TargetPath -ne (Join-Path $appPath 'ZaloFlow.exe')) { throw 'Incorrect shortcut target.' }
        if ($shortcut.IconLocation -notlike '*ZaloFlow.exe*') { throw 'Missing shortcut icon.' }
    }
    if (-not ((Get-Item "$appPath/_internal" -Force).Attributes -band [IO.FileAttributes]::Hidden)) { throw 'Support directory is not hidden.' }
}

function Assert-InstalledApp {
    $reportPath = Join-Path $env:RUNNER_TEMP 'zaloflow-installed-smoke.json'
    Remove-Item $reportPath -ErrorAction SilentlyContinue
    $process = Start-Process "$appPath/ZaloFlow.exe" -ArgumentList @('--smoke-test', '--smoke-report', "`"$reportPath`"") -PassThru
    if (-not $process.WaitForExit(90000)) { Stop-Process -Id $process.Id -Force; throw 'Installed app timed out.' }
    if ($process.ExitCode -ne 0) {
        if (Test-Path "$reportPath.log") { Get-Content "$reportPath.log" }
        throw 'Installed application smoke test failed.'
    }
    $report = Get-Content $reportPath -Raw | ConvertFrom-Json
    if (-not $report.ok -or -not $report.stopped -or -not $report.node_available -or -not $report.licensed -or -not $report.password_recovery) { throw 'Incomplete installed app smoke test.' }
}

$argsInstall = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$appPath`"")
try {
    Run-Installer $setup $argsInstall 'zaloflow-install.log'
    Assert-Shortcuts
    Assert-InstalledApp
    foreach ($folder in @('instance', 'license')) {
        New-Item -ItemType Directory "$dataPath/$folder" -Force | Out-Null
        Set-Content "$dataPath/$folder/installer-preservation-test.txt" "Keep $folder"
    }
    Run-Installer $setup $argsInstall 'zaloflow-upgrade.log'
    Assert-Shortcuts
    Assert-InstalledApp
    Run-Installer "$appPath/unins000.exe" @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'zaloflow-uninstall.log'
    if ((Test-Path "$appPath/ZaloFlow.exe") -or (Test-Path $desktopShortcut) -or (Test-Path $startShortcut)) { throw 'Uninstall left application or shortcuts behind.' }
    foreach ($folder in @('instance', 'license')) {
        if ((Get-Content "$dataPath/$folder/installer-preservation-test.txt" -Raw).Trim() -ne "Keep $folder") { throw 'Install/upgrade/uninstall damaged user data.' }
    }
    Write-Host 'PASS: install, Desktop/Start icons, hidden support files, installed application, upgrade, uninstall, data and activation preservation.'
} finally {
    # Only synthetic data created after the guard above, never real user data.
    Remove-Item $dataPath -Recurse -Force -ErrorAction SilentlyContinue
}
