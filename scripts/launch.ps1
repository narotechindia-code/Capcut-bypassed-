$ErrorActionPreference = 'Stop'
$script:ExitCode = 0
$script:TempWarp = $null

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

function Find-WarpCli {
    $cmd = Get-Command warp-cli.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command warp-cli -ErrorAction SilentlyContinue }
    if ($cmd) { return $cmd.Source }
    foreach ($p in @(
        (Join-Path $env:PROGRAMFILES 'Cloudflare\Cloudflare WARP\warp-cli.exe'),
        (Join-Path $env:PROGRAMFILES 'Cloudflare\Cloudflare One Client\warp-cli.exe'),
        (Join-Path ${env:PROGRAMFILES(X86)} 'Cloudflare\Cloudflare WARP\warp-cli.exe')
    )) { if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) { return $p } }
    return $null
}

function Run-Warp {
    param([string[]]$Args, [int]$TimeoutSec = 60)
    $cli = Find-WarpCli
    if (-not $cli) { throw 'warp-cli.exe was not found.' }
    $output = & $cli @Args 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "warp-cli $($Args -join ' ') failed (code $LASTEXITCODE): $($output.Trim())" }
    return $output
}

function Ensure-WarpInstalled {
    $cli = Find-WarpCli
    if ($cli) { return $cli }
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { $winget = Get-Command winget -ErrorAction SilentlyContinue }
    if (-not $winget) { throw 'Cloudflare WARP is required for the temporary installation VPN, but winget is not available.' }
    Write-Host '       Installing Cloudflare WARP...' -ForegroundColor Cyan
    & $winget.Source install --id Cloudflare.Warp --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Cloudflare WARP installation failed (code $LASTEXITCODE)." }
    for ($i=0; $i -lt 20; $i++) {
        $cli = Find-WarpCli
        if ($cli) { return $cli }
        Start-Sleep -Seconds 1
    }
    throw 'Cloudflare WARP installed but warp-cli.exe could not be found.'
}

function Start-TemporaryFullWarp {
    $cli = Ensure-WarpInstalled
    $status = (Run-Warp @('status')).ToLowerInvariant()
    $settings = (Run-Warp @('settings')).ToLowerInvariant()
    $wasConnected = ($status -match 'connected' -and $status -notmatch 'disconnected')
    $oldMode = 'warp'
    if ($settings -match 'warpproxy|local proxy|proxy') { $oldMode = 'proxy' }

    if (-not $wasConnected) {
        try { Run-Warp @('registration','show') | Out-Null } catch { Run-Warp @('registration','new') | Out-Null }
        Write-Host '       Enabling temporary full-device WARP...' -ForegroundColor Cyan
        Run-Warp @('mode','warp') | Out-Null
        Run-Warp @('connect') | Out-Null
        $connectedByUs = $true
    } else {
        Write-Host '       WARP is already connected; using the existing WARP tunnel for installation.' -ForegroundColor DarkGray
        $connectedByUs = $false
    }

    for ($i=0; $i -lt 30; $i++) {
        $s = (Run-Warp @('status')).ToLowerInvariant()
        if ($s -match 'connected' -and $s -notmatch 'disconnected') {
            return [pscustomobject]@{ Cli=$cli; ConnectedByUs=$connectedByUs; PreviousMode=$oldMode }
        }
        Start-Sleep -Seconds 1
    }
    throw 'Cloudflare WARP did not reach Connected state.'
}

function Stop-TemporaryFullWarp {
    param($Session)
    if (-not $Session -or -not $Session.ConnectedByUs) { return }
    try {
        Write-Host '       Turning temporary installation VPN OFF...' -ForegroundColor Cyan
        Run-Warp @('disconnect') | Out-Null
        if ($Session.PreviousMode -eq 'proxy') { Run-Warp @('mode','proxy') | Out-Null }
        else { Run-Warp @('mode','warp') | Out-Null }
    } catch { Write-Host "       WARNING: Could not fully restore WARP state: $($_.Exception.Message)" -ForegroundColor Yellow }
}

function Test-TrustedCapCutInstaller {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $sig = Get-AuthenticodeSignature -LiteralPath $Path
    if ($sig.Status -ne 'Valid') { return $false }
    return ([string]$sig.SignerCertificate.Subject -match '(?i)ByteDance')
}

function Download-CapCutInstallerThroughOfficialEndpoint {
    param([Parameter(Mandatory=$true)][string]$Destination)
    $url = 'https://www.capcut.com/activity/download_pc?__position__=top'
    Write-Host '       Downloading from CapCut official Windows download endpoint...' -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $url -OutFile $Destination -MaximumRedirection 10 -UseBasicParsing -Headers @{ 'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36' }
    } catch {
        throw "CapCut official download endpoint could not be fetched even with WARP: $($_.Exception.Message)"
    }

    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) { throw 'CapCut download endpoint did not produce a file.' }
    $item = Get-Item -LiteralPath $Destination
    if ($item.Length -lt 1MB) {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw 'CapCut returned a web page/redirect instead of the Windows installer. A browser session may be required to resolve the download URL.'
    }
    $bytes = [System.IO.File]::ReadAllBytes($Destination)
    if ($bytes.Length -lt 2 -or $bytes[0] -ne 0x4D -or $bytes[1] -ne 0x5A) {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw 'CapCut returned non-EXE content instead of the Windows installer.'
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

    # The Microsoft Store route is attempted first, but it is expected to be
    # unavailable in some regions.
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { $winget = Get-Command winget -ErrorAction SilentlyContinue }
    if ($winget) {
        Write-Host '       Trying the official Microsoft Store package...' -ForegroundColor Cyan
        & $winget.Source install --id XP9KN75RRB9NHS --exact --source msstore --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        Start-Sleep -Seconds 3
        $found = Find-CapCutExe
        if ($found) { return $found }
        Write-Host '       Store installation was unavailable or did not install CapCut.' -ForegroundColor Yellow
    }

    # IMPORTANT: this is the user's requested behavior. Full-device WARP is
    # enabled only for the installer download/install phase, then disconnected.
    $script:TempWarp = Start-TemporaryFullWarp
    try {
        Download-CapCutInstallerThroughOfficialEndpoint -Destination $installer | Out-Null
        Write-Host '       Official CapCut installer downloaded and signature verified.' -ForegroundColor Green
        Write-Host '       Starting CapCut installer...' -ForegroundColor Cyan
        $process = Start-Process -FilePath $installer -Wait -PassThru
        Write-Host "       Installer process exited with code $($process.ExitCode)." -ForegroundColor DarkGray
        $deadline = (Get-Date).AddMinutes(15)
        while ((Get-Date) -lt $deadline) {
            $found = Find-CapCutExe
            if ($found) { return $found }
            Start-Sleep -Seconds 2
        }
        throw 'CapCut installer finished, but CapCut.exe was not detected.'
    }
    finally {
        Stop-TemporaryFullWarp $script:TempWarp
        $script:TempWarp = $null
    }
}

try {
    Write-Host '=== CapCut Windows Launcher ===' -ForegroundColor Cyan
    Write-Host 'Bootstrap mode: temporary VPN installation flow' -ForegroundColor DarkGray
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
                try { & $command -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null; if ($LASTEXITCODE -eq 0) { return $command } } catch {}
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
    if ($script:TempWarp) { Stop-TemporaryFullWarp $script:TempWarp; $script:TempWarp = $null }
    Show-LauncherError $_
}
finally {
    Write-Host ''
    Write-Host 'Press ENTER to close this launcher window...' -ForegroundColor Cyan
    try { [void](Read-Host) } catch {}
}
