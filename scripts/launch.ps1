$ErrorActionPreference = 'Stop'
$script:ExitCode = 0

function Show-LauncherError {
    param([object]$ErrorRecord)
    Write-Host ''
    Write-Host '=== CapCut Launcher Error ===' -ForegroundColor Red
    Write-Host ($ErrorRecord.Exception.Message) -ForegroundColor Red
    Write-Host ''
    Write-Host 'The PowerShell window will remain open so you can read the error.' -ForegroundColor Yellow
}

try {
    Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan
    Write-Host 'Bootstrap mode: safe / non-closing' -ForegroundColor DarkGray

    if ($env:OS -ne 'Windows_NT') { throw 'This launcher supports Windows only.' }

    $repo = 'narotechindia-code/Capcut-bypassed-'
    $rawBase = "https://raw.githubusercontent.com/$repo/main"
    $installRoot = Join-Path $env:LOCALAPPDATA 'CapCutBypassedLauncher'
    $venv = Join-Path $installRoot '.venv'
    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null

    function Find-Python {
        foreach ($command in @('py', 'python')) {
            $cmd = Get-Command $command -ErrorAction SilentlyContinue
            if ($cmd) {
                try {
                    & $command -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { return $command }
                } catch {}
            }
        }
        return $null
    }

    Write-Host '[1/5] Checking Python...' -ForegroundColor Cyan
    $python = Find-Python
    if (-not $python) {
        Write-Host 'Python 3.10+ was not found.' -ForegroundColor Yellow
        Write-Host 'Install Python 3.10+ from the official Python distribution, then rerun this launcher.'
        $script:ExitCode = 11
        return
    }
    Write-Host "       Found: $python" -ForegroundColor Green

    Write-Host '[2/5] Downloading launcher files...' -ForegroundColor Cyan
    $launcherDir = Join-Path $installRoot 'launcher'
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
    $files = @('launcher/__init__.py', 'launcher/main.py', 'launcher/capcut.py', 'launcher/network.py', 'launcher/vpn.py', 'requirements.txt')
    foreach ($file in $files) {
        $target = Join-Path $installRoot $file
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Invoke-WebRequest -Uri "$rawBase/$file" -OutFile $target
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Failed to download required file: $file" }
    }
    Write-Host '       Download complete.' -ForegroundColor Green

    $mainPy = Join-Path $installRoot 'launcher\main.py'
    $initPy = Join-Path $installRoot 'launcher\__init__.py'
    if (-not (Test-Path -LiteralPath $mainPy -PathType Leaf) -or -not (Test-Path -LiteralPath $initPy -PathType Leaf)) { throw "Launcher package is incomplete. Expected files under: $launcherDir" }

    Write-Host '[3/5] Preparing isolated Python environment...' -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
    }
    $venvPython = Join-Path $venv 'Scripts/python.exe'
    & $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $installRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to prepare Python dependencies.' }
    Write-Host '       Python environment ready.' -ForegroundColor Green

    Write-Host '[4/5] Starting launcher...' -ForegroundColor Cyan
    Write-Host "       Application root: $installRoot" -ForegroundColor DarkGray
    Write-Host "       Python: $venvPython" -ForegroundColor DarkGray

    # Execute the downloaded file directly. This removes Python package discovery
    # from the bootstrap path completely and works regardless of the caller's cwd.
    & $venvPython $mainPy
    $script:ExitCode = $LASTEXITCODE

    Write-Host '[5/5] Launcher finished.' -ForegroundColor Green
    if ($script:ExitCode -ne 0) { Write-Host "Launcher exit code: $script:ExitCode" -ForegroundColor Yellow }
}
catch {
    $script:ExitCode = 1
    Show-LauncherError $_
}
finally {
    Write-Host ''
    Write-Host 'Press ENTER to close this launcher window...' -ForegroundColor Cyan
    try { [void](Read-Host) } catch {}
}
