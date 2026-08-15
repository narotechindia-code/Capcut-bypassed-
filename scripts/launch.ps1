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

function Find-CapCutExe {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'CapCut\Apps\CapCut.exe'),
        (Join-Path $env:LOCALAPPDATA 'CapCut\CapCut.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\CapCut\CapCut.exe'),
        (Join-Path $env:PROGRAMFILES 'CapCut\Apps\CapCut.exe'),
        (Join-Path ${env:PROGRAMFILES(X86)} 'CapCut\Apps\CapCut.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    foreach ($root in @($env:LOCALAPPDATA, $env:PROGRAMFILES, ${env:PROGRAMFILES(X86)}) | Where-Object { $_ -and (Test-Path $_) }) {
        try {
            $hit = Get-ChildItem -LiteralPath $root -Filter 'CapCut.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { return $hit.FullName }
        } catch {}
    }
    return $null
}

try {
    Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan
    Write-Host 'Bootstrap mode: repaired official-installer flow' -ForegroundColor DarkGray
    if ($env:OS -ne 'Windows_NT') { throw 'This launcher supports Windows only.' }

    $repo = 'narotechindia-code/Capcut-bypassed-'
    $rawBase = "https://raw.githubusercontent.com/$repo/main"
    $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString()
    $installRoot = Join-Path $env:LOCALAPPDATA 'CapCutBypassedLauncher'
    $downloadDir = Join-Path $installRoot 'downloads'
    $venv = Join-Path $installRoot '.venv'
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

    function Find-Python {
        foreach ($command in @('py', 'python')) {
            if (Get-Command $command -ErrorAction SilentlyContinue) {
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
        throw 'Python 3.10+ is required. Automatic Python installation is not available from this bootstrap yet.'
    }
    Write-Host "       Found: $python" -ForegroundColor Green

    Write-Host '[2/5] Checking CapCut...' -ForegroundColor Cyan
    $capcutExe = Find-CapCutExe

    if (-not $capcutExe) {
        Write-Host '       CapCut is not installed.' -ForegroundColor Yellow
        Write-Host '       Opening the official CapCut Windows download page...' -ForegroundColor Cyan
        $officialPage = 'https://www.capcut.com/resource/capcut-for-windows'
        Start-Process $officialPage | Out-Null
        Write-Host ''
        Write-Host '       CapCut does not provide a verified public Windows installer URL or silent-install switch here.' -ForegroundColor Yellow
        Write-Host '       Download CapCut_Setup.exe from the official page, run it, and complete the normal installation.' -ForegroundColor Yellow
        Write-Host '       This launcher will automatically continue once CapCut.exe appears.' -ForegroundColor Cyan
        Write-Host ''

        $deadline = (Get-Date).AddMinutes(15)
        while ((Get-Date) -lt $deadline) {
            $capcutExe = Find-CapCutExe
            if ($capcutExe) { break }
            Write-Host -NoNewline '.'
            Start-Sleep -Seconds 3
        }
        Write-Host ''
        if (-not $capcutExe) {
            throw 'CapCut was not detected after 15 minutes. Finish the official installation, then run the launcher again.'
        }
    }

    Write-Host "       CapCut detected: $capcutExe" -ForegroundColor Green
    $env:CAPCUT_EXE = $capcutExe

    Write-Host '[3/5] Downloading launcher files...' -ForegroundColor Cyan
    $launcherDir = Join-Path $installRoot 'launcher'
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
    foreach ($file in @('launcher/__init__.py','launcher/main.py','launcher/capcut.py','launcher/network.py','launcher/vpn.py','requirements.txt')) {
        $target = Join-Path $installRoot $file
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Invoke-WebRequest -Uri "$rawBase/$file?v=$cacheBust" -OutFile $target -Headers @{ 'Cache-Control'='no-cache'; 'Pragma'='no-cache' }
    }

    Write-Host '[4/5] Preparing Python environment...' -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
    }
    $venvPython = Join-Path $venv 'Scripts/python.exe'
    & $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $installRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to prepare Python dependencies.' }

    Write-Host '[5/5] Starting CapCut network launcher...' -ForegroundColor Cyan
    & $venvPython (Join-Path $installRoot 'launcher\main.py')
    $script:ExitCode = $LASTEXITCODE
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
