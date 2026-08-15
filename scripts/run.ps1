$ErrorActionPreference = 'Stop'

Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan

if ($env:OS -ne 'Windows_NT') {
    throw 'This launcher supports Windows only.'
}

$repo = 'narotechindia-code/Capcut-bypassed-'
$rawBase = "https://raw.githubusercontent.com/$repo/main"
$installRoot = Join-Path $env:LOCALAPPDATA 'CapCutBypassedLauncher'
$venv = Join-Path $installRoot '.venv'

New-Item -ItemType Directory -Force -Path $installRoot | Out-Null

function Find-Python {
    $commands = @('py', 'python')
    foreach ($command in $commands) {
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

$python = Find-Python
if (-not $python) {
    Write-Host 'Python 3.10+ was not found.' -ForegroundColor Yellow
    Write-Host 'Automatic Python installation is intentionally not performed from an arbitrary download URL.'
    Write-Host 'Install Python 3.10+ from the official Python distribution, then rerun this command.'
    exit 11
}

$launcherDir = Join-Path $installRoot 'launcher'
New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

$files = @('launcher/__init__.py', 'launcher/main.py', 'launcher/capcut.py', 'launcher/network.py', 'requirements.txt')
foreach ($file in $files) {
    $target = Join-Path $installRoot $file
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Invoke-WebRequest -Uri "$rawBase/$file" -OutFile $target
}

if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) {
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
}

$venvPython = Join-Path $venv 'Scripts/python.exe'

& $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $installRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to prepare Python dependencies.' }

Write-Host 'Running launcher...' -ForegroundColor Green
& $venvPython -m launcher.main @args
exit $LASTEXITCODE
