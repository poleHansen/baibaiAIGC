param(
  [string]$PythonExe = ".venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot $PythonExe

if (-not (Test-Path $pythonPath)) {
  throw "Python executable not found: $pythonPath"
}

$binDir = Join-Path $repoRoot "app/bin"
$buildDir = Join-Path $repoRoot "build/pyinstaller"
$specDir = Join-Path $repoRoot "build/pyinstaller/spec"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
New-Item -ItemType Directory -Force -Path $specDir | Out-Null

& $pythonPath -m pip install pyinstaller | Out-Host

& $pythonPath -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name app_service `
  --distpath $binDir `
  --workpath (Join-Path $buildDir "work") `
  --specpath $specDir `
  --paths (Join-Path $repoRoot "scripts") `
  --collect-submodules encodings `
  --hidden-import encodings `
  --hidden-import app_config `
  --hidden-import aigc_records `
  --hidden-import aigc_round_service `
  --hidden-import chunking `
  --hidden-import docx_pipeline `
  --hidden-import llm_client `
  --hidden-import runtime_paths `
  --hidden-import skill_round_helper `
(Join-Path $repoRoot "scripts/app_service.py")

Write-Host "Built backend executable: $(Join-Path $binDir 'app_service.exe')"