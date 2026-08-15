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
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    foreach ($root in @($env:LOCALAPPDATA, $env:PROGRAMFILES, ${env:PROGRAMFILES(X86)}) | Where-Object { $_ -and (Test-Path $_) }) {
        try {
            $hit = Get-ChildItem -LiteralPath $root -Filter 'CapCut.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { return $hit.FullName }
        } catch {}
    }
    return $null
}

function Test-TrustedCapCutInstaller {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $sig = Get-AuthenticodeSignature -LiteralPath $Path
    if ($sig.Status -ne 'Valid') { return $false }
    $subject = [string]$sig.SignerCertificate.Subject
    return ($subject -match '(?i)ByteDance')
}

function Download-OfficialCapCutInstaller {
    param([Parameter(Mandatory=$true)][string]$Destination)

    # This is CapCut's own US package CDN, not a mirror. The pinned build is
    # used only as an installation fallback because CapCut does not expose a
    # stable documented direct-installer API. The installer is signature-checked
    # before it is executed. If the CDN removes this build, fail safely rather
    # than downloading an unknown third-party executable.
    $url = 'https://lf16-capcut.faceulv.com/obj/capcutpc-packages-us/packages/CapCut_7_5_0_3053_capcutpc_0_creatortool.exe'

    Write-Host '       Trying CapCut official package CDN...' -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $url -OutFile $Destination -UseBasicParsing
    } catch {
        throw "Could not download the CapCut installer from the official package CDN: $($_.Exception.Message)"
    }

    if (-not (Test-TrustedCapCutInstaller -Path $Destination)) {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw 'The downloaded CapCut installer failed the Windows Authenticode/ByteDance signature check. It was NOT executed.'
    }

    return $Destination
}

function Install-CapCut {
    param([Parameter(Mandatory=$true)][string]$DownloadDir)

    $installer = Join-Path $DownloadDir 'CapCut_Setup.exe'

    # First try the Microsoft Store package. This is official, but Windows may
    # reject it in regions where CapCut is unavailable.
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { $winget = Get-Command winget -ErrorAction SilentlyContinue }
    if ($winget) {
        Write-Host '       Trying the official Microsoft Store package...' -ForegroundColor Cyan
        & $winget.Source install --id XP9KN75RRB9NHS --exact --source msstore --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        $code = $LASTEXITCODE
        Start-Sleep -Seconds 3
        $found = Find-CapCutExe
        if ($found) { return $found }
        Write-Host "       Microsoft Store installation was not available/successful (code $code)." -ForegroundColor Yellow
    }

    # Fall back to CapCut's own package CDN. This is the important path for
    # machines where the India-region website/store does not expose CapCut.
    Download-OfficialCapCutInstaller -Destination $installer | Out-Null
    Write-Host '       Official CapCut installer downloaded and signature verified.' -ForegroundColor Green
    Write-Host '       Starting CapCut installer...' -ForegroundColor Cyan

    $process = Start-Process -FilePath $installer -Wait -PassThru
    Write-Host "       Installer process exited with code $($process.ExitCode)." -ForegroundColor DarkGray

    $deadline = (Get-Date).AddMinutes(10)
    while ((Get-Date) -lt $deadline) {
        $found = Find-CapCutExe
        if ($found) { return $found }
        Start-Sleep -Seconds 2
    }

    throw 'The official CapCut installer finished, but CapCut.exe was not detected. The installation may have been blocked or may require a restart.'
}

try {
    Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan
    Write-Host 'Bootstrap mode: repaired automatic-install flow' -ForegroundColor DarkGray
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
    if (-not $python) { throw 'Python 3.10+ is required. Install Python, then rerun the launcher.' }
    Write-Host "       Found: $python" -ForegroundColor Green

    Write-Host '[2/5] Checking / installing CapCut...' -ForegroundColor Cyan
    $capcutExe = Find-CapCutExe
    if (-not $capcutExe) {
        Write-Host '       CapCut is not installed.' -ForegroundColor Yellow
        $capcutExe = Install-CapCut -DownloadDir $downloadDir
    }

    Write-Host "       CapCut ready: $capcutExe" -ForegroundColor Green
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
