$ErrorActionPreference="Stop"
$root=Resolve-Path "$PSScriptRoot\..";$b=Join-Path $root "backend";$f=Join-Path $root "frontend"
if(-not(Test-Path "$b\.venv\Scripts\python.exe")){throw "Run install.ps1 first"}
Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$b'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Sleep 2
Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$f'; npm run dev"
Start-Sleep 3
Start-Process "http://127.0.0.1:5173"
