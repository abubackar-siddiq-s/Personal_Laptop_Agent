<#
.SYNOPSIS
    LAPTOP AI - One-Click Windows Startup Script
.DESCRIPTION
    Detects already-running backend/frontend processes, initializes Uvicorn and Vite if needed,
    waits for health readiness, creates a single-use setup ticket for trusted local onboarding,
    and opens the personal workspace in your default web browser.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   LAPTOP AI - Personal Windows Agentic AI Workspace" -ForegroundColor Cyan
Write-Host "   Single-User ThinkPad Edition" -ForegroundColor Gray
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Resolve Python interpreter
$PythonExe = Join-Path $ScriptDir "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python.exe"
}

# 2. Check if Backend (Port 8000) is running and healthy
$BackendRunning = $false
try {
    $hCheck = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -Method Get -TimeoutSec 1 -ErrorAction SilentlyContinue
    if ($hCheck -and ($hCheck.ok -or $hCheck.status -eq "ok")) {
        $BackendRunning = $true
    }
} catch {}

$BackendProc = $null
if (-not $BackendRunning) {
    Write-Host "[1/4] Starting LAPTOP AI backend service (uvicorn)..." -ForegroundColor Yellow
    $BackendDir = Join-Path $ScriptDir "backend"
    $BackendProc = Start-Process -FilePath $PythonExe `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $BackendDir `
        -WindowStyle Minimized `
        -PassThru
} else {
    Write-Host "[1/4] Backend service is already running on port 8000." -ForegroundColor Green
}

# 3. Wait for Backend Readiness (GET /api/health with 30s timeout)
Write-Host "[2/4] Waiting for backend readiness..." -ForegroundColor Yellow
$BackendReady = $false
$Retries = 0
$MaxRetries = 50  # 50 * 600ms = 30 seconds

while (-not $BackendReady -and $Retries -lt $MaxRetries) {
    Start-Sleep -Milliseconds 600
    $Retries++
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($health -and ($health.ok -or $health.status -eq "ok")) {
            $BackendReady = $true
        }
    } catch {}
}

if (-not $BackendReady) {
    Write-Host "[ERROR] Backend service failed to become ready within 30 seconds." -ForegroundColor Red
    if ($BackendProc -and -not $BackendProc.HasExited) {
        Write-Host "[CLEANUP] Terminating unresponsive backend process $($BackendProc.Id)..." -ForegroundColor Yellow
        Stop-Process -Id $BackendProc.Id -Force -ErrorAction SilentlyContinue
    }
    exit 1
}
Write-Host "[2/4] Backend is ready and healthy." -ForegroundColor Green

# 4. Check if Frontend (Port 5173) is running
$FrontendRunning = $false
try {
    $conn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    if ($conn) { $FrontendRunning = $true }
} catch {}

$FrontendProc = $null
if (-not $FrontendRunning) {
    Write-Host "[3/4] Starting LAPTOP AI UI interface (vite)..." -ForegroundColor Yellow
    $FrontendDir = Join-Path $ScriptDir "frontend"
    $FrontendProc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm run dev" `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Minimized `
        -PassThru
    
    # Wait for Vite dev server readiness (max 30 seconds)
    $FrontendReady = $false
    $FRetries = 0
    $MaxFRetries = 50
    while (-not $FrontendReady -and $FRetries -lt $MaxFRetries) {
        Start-Sleep -Milliseconds 600
        $FRetries++
        try {
            $fTest = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
            if ($fTest) { $FrontendReady = $true }
        } catch {}
    }
    if (-not $FrontendReady) {
        Write-Host "[ERROR] Frontend UI failed to become ready within 30 seconds." -ForegroundColor Red
        if ($FrontendProc -and -not $FrontendProc.HasExited) {
            Write-Host "[CLEANUP] Terminating unresponsive frontend launcher $($FrontendProc.Id)..." -ForegroundColor Yellow
            Stop-Process -Id $FrontendProc.Id -Force -ErrorAction SilentlyContinue
        }
        exit 1
    }
} else {
    Write-Host "[3/4] Frontend interface is already running on port 5173." -ForegroundColor Green
}

# 5. Generate single-use local setup ticket
Write-Host "[4/4] Establishing secure local session..." -ForegroundColor Yellow
$SetupTicket = ""
try {
    $pyCmd = "import sys; sys.path.insert(0, 'backend'); from app.core.security import create_setup_ticket; print(create_setup_ticket(120))"
    $ticketOutput = & $PythonExe -c $pyCmd 2>$null
    if ($ticketOutput) {
        $SetupTicket = $ticketOutput.Trim()
    }
} catch {}

$LaunchUrl = "http://127.0.0.1:5173"
if ($SetupTicket -ne "") {
    $LaunchUrl = "http://127.0.0.1:5173/?setup_ticket=$SetupTicket"
}

Write-Host "Opening LAPTOP AI in your default browser..." -ForegroundColor Green
Start-Process $LaunchUrl

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   LAPTOP AI is now active!" -ForegroundColor Green
Write-Host "   Workspace URL: http://127.0.0.1:5173" -ForegroundColor White
Write-Host "   Sessions persist for 30 days automatically." -ForegroundColor Gray
Write-Host "========================================================" -ForegroundColor Cyan

