param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$rootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$appDir = Join-Path $rootDir "app"
$venvDir = Join-Path $rootDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvActivate = Join-Path $venvDir "Scripts\Activate.ps1"

function Test-PythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-Venv {
    if (Test-Path $venvPython) {
        return
    }

    Write-Host "Creating virtual environment in .venv ..."
    if (Test-PythonCommand -Name "py") {
        & py -3 -m venv $venvDir
        return
    }

    if (Test-PythonCommand -Name "python") {
        & python -m venv $venvDir
        return
    }

    throw "Python 3 was not found. Install Python 3 first, then rerun this script."
}

function Install-BackendDependencies {
    Write-Host "Installing backend dependencies ..."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $rootDir "requirements.txt")
}

function Install-FrontendDependencies {
    Write-Host "Installing frontend dependencies ..."
    Push-Location $appDir
    try {
        npm install
    }
    finally {
        Pop-Location
    }
}

function Start-ServiceWindow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-EncodedCommand",
        $encodedCommand
    ) -WorkingDirectory $rootDir | Out-Null
    Write-Host "$Title started."
}

Ensure-Venv

if (-not $SkipInstall) {
    Install-BackendDependencies
    Install-FrontendDependencies
}

$backendCommand = @"
Set-Location '$rootDir'
Write-Host 'Starting backend on http://127.0.0.1:8765'
& '$venvPython' 'scripts/web_app.py'
"@

$frontendCommand = @"
Set-Location '$appDir'
if (Test-Path '$venvActivate') {
    Write-Host 'Using Python virtual environment from $venvDir'
}
Write-Host 'Starting frontend on http://127.0.0.1:1420'
npm run dev:web
"@

Start-ServiceWindow -Title "Backend" -Command $backendCommand
Start-ServiceWindow -Title "Frontend" -Command $frontendCommand

Write-Host ""
Write-Host "Web backend:  http://127.0.0.1:8765"
Write-Host "Web frontend: http://127.0.0.1:1420"
Write-Host ""
Write-Host "If dependencies are already installed, run:"
Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\start_web_dev.ps1 -SkipInstall"
