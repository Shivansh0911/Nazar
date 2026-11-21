<#
.SYNOPSIS
  Start everything for the local demo, each service in its own window:
  Docker (Postgres + MediaMTX), worker, API (:8000) and the web app (:3000).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
#>
param([switch]$DevWeb)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

# 1. Docker Desktop + containers
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $dd = @("$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe", "C:\Program Files\Docker\Docker\Docker Desktop.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $dd) { throw "Docker Desktop not found - start it manually" }
  Write-Host "Starting Docker Desktop..."
  Start-Process $dd
  $deadline = (Get-Date).AddMinutes(3)
  do { Start-Sleep -Seconds 5; docker info *> $null } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
  if ($LASTEXITCODE -ne 0) { throw "Docker did not start within 3 minutes" }
}
docker compose -f (Join-Path $root "infra\docker-compose.yml") up -d
Write-Host "Waiting for Postgres..."
$deadline = (Get-Date).AddMinutes(2)
do { Start-Sleep -Seconds 2; $h = docker inspect -f "{{.State.Health.Status}}" nazar-postgres-1 2>$null } until ($h -eq "healthy" -or (Get-Date) -gt $deadline)

# 2. services
$backend = Join-Path $root "backend"
Start-Process powershell -WorkingDirectory $backend -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Nazar worker'; & '$py' -m nazar.worker.run"
Start-Process powershell -WorkingDirectory $backend -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Nazar API'; & '$py' -m uvicorn nazar.api.main:app --host 0.0.0.0 --port 8000"
$web = Join-Path $root "web"
if ($DevWeb -or -not (Test-Path (Join-Path $web "out\index.html"))) {
  Start-Process powershell -WorkingDirectory $web -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Nazar web'; npm run dev"
} else {
  Start-Process powershell -WorkingDirectory (Join-Path $web "out") -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Nazar web'; & '$py' -m http.server 3000"
}
Write-Host ""
Write-Host "Nazar is starting:  http://localhost:3000   (passcode from .env DEMO_PASSCODE, default nazar2026)"
Write-Host "API: http://localhost:8000/api/health"
