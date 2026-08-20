$ErrorActionPreference = 'Stop'
$script:ExitCode = 0

function Show-LauncherError {
    param([object]$ErrorRecord)
    Write-Host ''
    Write-Host '=== CapCut Launcher Error ===' -ForegroundColor Red
    Write-Host ($ErrorRecord.Exception.Message) -ForegroundColor Red
    Write-Host ''
    Write-Host "Launcher log: $env:LOCALAPPDATA\CapCutBypassedLauncher\logs\launcher.log" -ForegroundColor Yellow
}

function Pause-Launcher {
    Write-Host ''
    Write-Host 'Press ENTER to close this launcher window...' -ForegroundColor Cyan
    try { [void](Read-Host) } catch { Start-Sleep -Seconds 3 }
}

try {
    Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan
    Write-Host 'Mode: process-only VPN; Windows default routing is not intentionally changed.' -ForegroundColor DarkGray

    if ($env:OS -ne 'Windows_NT') { throw 'This launcher supports Windows only.' }

    $repo = 'narotechindia-code/Capcut-bypassed-'
    $rawBase = "https://raw.githubusercontent.com/$repo/main"
    $installRoot = Join-Path $env:LOCALAPPDATA 'CapCutBypassedLauncher'
    $venv = Join-Path $installRoot '.venv'
    $selfFile = Join-Path $installRoot 'run.ps1'
    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null

    function Find-Python {
        foreach ($command in @('py', 'python')) {
            $cmd = Get-Command $command -ErrorAction SilentlyContinue
            if ($cmd) {
                try {
                    & $command -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { return $cmd.Source }
                } catch {}
            }
        }
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
            (Join-Path $env:ProgramFiles 'Python312\python.exe'),
            (Join-Path $env:ProgramFiles 'Python311\python.exe')
        )
        foreach ($path in $candidates) {
            if (Test-Path -LiteralPath $path) { return $path }
        }
        return $null
    }

    Write-Host '[1/5] Checking Python 3.10+...' -ForegroundColor Cyan
    $python = Find-Python
    if (-not $python) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Python was not found and winget is unavailable. Install Microsoft App Installer, then rerun.' }
        Write-Host '       Python not found. Installing Python 3.12 automatically through WinGet...' -ForegroundColor Yellow
        & $winget.Source install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -notin @(0, 0x8A150014)) { throw "Automatic Python installation failed (winget exit code $LASTEXITCODE)." }
        Start-Sleep -Seconds 2
        $python = Find-Python
        if (-not $python) { throw 'Python installation completed but python.exe could not be located.' }
    }
    Write-Host "       Python: $python" -ForegroundColor Green

    Write-Host '[2/5] Downloading launcher files...' -ForegroundColor Cyan
    $files = @('launcher/__init__.py', 'launcher/main.py', 'launcher/capcut.py', 'launcher/network.py', 'launcher/vpn.py', 'requirements.txt')
    foreach ($file in $files) {
        $target = Join-Path $installRoot $file
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Invoke-WebRequest -Uri "$rawBase/$file" -OutFile $target
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Failed to download required file: $file" }
    }
    # Always save a real script file. This is critical when the command was
    # started as `irm ... | iex`, because $PSCommandPath is otherwise empty.
    Invoke-WebRequest -Uri "$rawBase/scripts/run.ps1" -OutFile $selfFile
    Write-Host '       Download complete.' -ForegroundColor Green

    Write-Host '[3/5] Preparing isolated Python environment...' -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
    }
    $venvPython = Join-Path $venv 'Scripts/python.exe'
    & $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $installRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to prepare Python dependencies.' }
    Write-Host '       Python environment ready.' -ForegroundColor Green

    # Elevate BEFORE Python starts. The elevated child is waited on, so there
    # is no detached Python process that appears and then immediately closes.
    $needsAdmin = $true
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        $needsAdmin = -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { $needsAdmin = $true }

    if ($needsAdmin) {
        Write-Host '[4/5] Requesting Administrator permission for process-only VPN...' -ForegroundColor Yellow
        $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $selfFile)
        $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -Verb RunAs -Wait -PassThru
        $script:ExitCode = $child.ExitCode
        Write-Host "Elevated launcher finished with exit code $script:ExitCode." -ForegroundColor Green
    }
    else {
        Write-Host '[4/5] Starting launcher...' -ForegroundColor Cyan
        $bootstrapCode = @"
import sys
from pathlib import Path
root = Path(r'''$installRoot''')
sys.path.insert(0, str(root))
import launcher.main
raise SystemExit(launcher.main.main())
"@
        & $venvPython -u -c $bootstrapCode @args
        $script:ExitCode = $LASTEXITCODE
    }

    Write-Host '[5/5] Launcher finished.' -ForegroundColor Green
    if ($script:ExitCode -ne 0) { Write-Host "Launcher exit code: $script:ExitCode" -ForegroundColor Yellow }
}
catch {
    $script:ExitCode = 1
    Show-LauncherError $_
}
finally {
    Pause-Launcher
}

# Deliberately no 'exit': safe for interactive PowerShell and `irm ... | iex`.
