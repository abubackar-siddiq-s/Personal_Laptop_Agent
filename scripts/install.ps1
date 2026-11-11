$ErrorActionPreference="Stop"
if(-not(Get-Command py -ErrorAction SilentlyContinue) -and -not(Get-Command python -ErrorAction SilentlyContinue)){throw "Install Python 3.11+"}
if(-not(Get-Command node -ErrorAction SilentlyContinue)){throw "Install Node.js 20+"}
Push-Location "$PSScriptRoot\..\backend"
if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv .venv
} else {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if(-not(Test-Path .env)){Copy-Item .env.example .env}
Pop-Location
Push-Location "$PSScriptRoot\..\frontend"
npm install
Pop-Location
Write-Host "Install complete. Run scripts\start.ps1" -ForegroundColor Green
