# ============================================================
#  Smart Traffic -- Data Collection  /  Build Script
#  Usage:
#    Double-click build_exe.bat
#    -- OR --
#    From Anaconda Prompt / PowerShell:
#      powershell -ExecutionPolicy Bypass -File build_exe.ps1
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step-Failed([string]$msg) {
    Write-Host ""
    Write-Host "[ERROR] $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  Smart Traffic -- Data Collection  /  Build Script"
Write-Host "============================================================"
Write-Host ""

# ----------------------------------------------------------------
# Step 0: Check tools
# ----------------------------------------------------------------

Write-Host "[0/5] Checking Python / Node.js / npm ..."
Write-Host ""

try   { $v = (python --version 2>&1); Write-Host "  Python : $v" }
catch { Step-Failed "Python not found. Install Python 3.10+ and add to PATH. If using Anaconda, run from Anaconda Prompt." }

try   { $v = (node --version 2>&1);   Write-Host "  Node   : $v" }
catch { Step-Failed "Node.js not found. Install Node.js 18+ from https://nodejs.org/" }

try   { $v = (npm --version 2>&1);    Write-Host "  npm    : $v" }
catch { Step-Failed "npm not found. Check your Node.js installation." }

Write-Host ""

# ----------------------------------------------------------------
# Step 1: Install Python dependencies
# ----------------------------------------------------------------

Write-Host "[1/5] Installing Python dependencies ..."
Write-Host ""

python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Step-Failed "pip install -r requirements.txt failed." }

python -m pip install -r google_interface\backend\requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Step-Failed "pip install google_interface\backend\requirements.txt failed." }

Write-Host "  Done."
Write-Host ""

# ----------------------------------------------------------------
# Step 2: Install PyInstaller
# ----------------------------------------------------------------

Write-Host "[2/5] Installing PyInstaller ..."
Write-Host ""

python -m pip install pyinstaller --quiet
if ($LASTEXITCODE -ne 0) { Step-Failed "PyInstaller install failed." }

Write-Host "  Done."
Write-Host ""

# ----------------------------------------------------------------
# Step 3: Build frontend  (npm install + npm run build)
# ----------------------------------------------------------------

Write-Host "[3/5] Building frontend (React -> static files) ..."
Write-Host "      First run may take a few minutes for npm install."
Write-Host ""

Push-Location google_interface\frontend

npm install
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Step-Failed "npm install failed."
}

npm run build
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Step-Failed "npm run build failed."
}

Pop-Location

if (-not (Test-Path "google_interface\frontend\dist\index.html")) {
    Step-Failed "Build finished but dist\index.html not found. Check vite.config.js."
}

Write-Host ""
Write-Host "  Done. -> google_interface\frontend\dist\"
Write-Host ""

# ----------------------------------------------------------------
# Step 4: Package with PyInstaller
# ----------------------------------------------------------------

Write-Host "[4/5] Running PyInstaller  (may take 3-8 minutes) ..."
Write-Host ""

python -m PyInstaller "Data Collection.spec" --noconfirm
if ($LASTEXITCODE -ne 0) { Step-Failed "PyInstaller failed. See output above." }

# ----------------------------------------------------------------
# Step 5: Done
# ----------------------------------------------------------------

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  [5/5] BUILD SUCCESSFUL" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Output folder:"
Write-Host "    $PSScriptRoot\dist\Data Collection\"
Write-Host ""
Write-Host "  Deployment steps:"
Write-Host "    1. Copy the entire  dist\Data Collection\  folder to the target PC."
Write-Host "    2. Create a  .env  file inside that folder:"
Write-Host "          AZURE_MAPS_KEY=your_azure_key_here"
Write-Host "    3. Double-click  Data Collection.exe"
Write-Host ""
Write-Host "  Note: .env must be next to Data Collection.exe"
Write-Host ""
