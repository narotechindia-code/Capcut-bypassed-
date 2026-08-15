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

    try {
        $locations = @(
            'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
        )
        foreach ($item in Get-ItemProperty $locations -ErrorAction SilentlyContinue) {
            if ($item.DisplayName -like '*CapCut*' -and $item.InstallLocation) {
                $hit = Get-ChildItem -LiteralPath $item.InstallLocation -Filter 'CapCut.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($hit) { return $hit.FullName }
            }
        }
    } catch {}

    return $null
}

try {
    Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan
    Write-Host 'Bootstrap mode: safe / non-closing' -ForegroundColor DarkGray

    if ($env:OS -ne 'Windows_NT') { throw 'This launcher supports Windows only.' }

    $repo = 'narotechindia-code/Capcut-bypassed-'
    $rawBase = "https://raw.githubusercontent.com/$repo/main"
    $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString()
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

    Write-Host '[2/5] Preparing CapCut and launcher files...' -ForegroundColor Cyan

    # Install CapCut here, in the PowerShell bootstrap itself. This guarantees
    # installation happens even if an older cached Python launcher is returned.
    $capcutExe = Find-CapCutExe
    if (-not $capcutExe) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { $winget = Get-Command winget -ErrorAction SilentlyContinue }
        if (-not $winget) {
            throw "CapCut is not installed and Windows Package Manager (winget) is unavailable. Install/update Microsoft's App Installer, then rerun the launcher."
        }

        Write-Host '       CapCut is not installed.' -ForegroundColor Yellow
        Write-Host '       Installing the official CapCut package through WinGet...' -ForegroundColor Cyan
        & $winget.Source install --id ByteDance.CapCut --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        $wingetCode = $LASTEXITCODE
        if ($wingetCode -ne 0 -and $wingetCode -ne 0x8A150014) {
            throw "CapCut installation failed. WinGet exit code: $wingetCode"
        }

        Write-Host '       Waiting for CapCut installation to become visible...' -ForegroundColor Cyan
        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline) {
            $capcutExe = Find-CapCutExe
            if ($capcutExe) { break }
            Start-Sleep -Seconds 2
        }
        if (-not $capcutExe) {
            throw 'WinGet completed, but CapCut.exe could not be located. The installer may require a restart or a user-session refresh.'
        }
        Write-Host "       CapCut installed: $capcutExe" -ForegroundColor Green
    }
    else {
        Write-Host "       CapCut already installed: $capcutExe" -ForegroundColor Green
    }

    # Pass the detected executable to Python so even older detector code can
    # launch the exact installation found by this bootstrapper.
    $env:CAPCUT_EXE = $capcutExe

    $launcherDir = Join-Path $installRoot 'launcher'
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
    $files = @('launcher/__init__.py', 'launcher/main.py', 'launcher/capcut.py', 'launcher/network.py', 'launcher/vpn.py', 'requirements.txt')
    foreach ($file in $files) {
        $target = Join-Path $installRoot $file
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Invoke-WebRequest -Uri "$rawBase/$file?v=$cacheBust" -OutFile $target -Headers @{ 'Cache-Control' = 'no-cache'; 'Pragma' = 'no-cache' }
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Failed to download required file: $file" }
    }
    Write-Host '       Launcher files ready.' -ForegroundColor Green

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
    Write-Host "       CapCut: $env:CAPCUT_EXE" -ForegroundColor DarkGray

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
