<#
.SYNOPSIS
  Smoke test against running services (starts nothing): health, cameras, a text ask, a rule compile, metrics.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
#>
param(
  [string]$Api = "http://localhost:8000",
  [string]$Passcode = "",
  [string]$Question = "Kal raat 10 baje ke baad shop counter pe kitne log aaye?",
  [string]$RuleCamera = "office-desk",
  [string]$RuleText = "Jab bhi koi desk 14 se bag uthaye, mujhe batana"
)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Passcode) {
  $envFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
  $line = (Get-Content $envFile -ErrorAction SilentlyContinue | Where-Object { $_ -match "^DEMO_PASSCODE=" }) | Select-Object -First 1
  $Passcode = if ($line) { $line.Split("=", 2)[1].Trim() } else { "nazar2026" }
  if (-not $Passcode) { $Passcode = "nazar2026" }
}
$results = @()
function Check($name, [scriptblock]$body) {
  try {
    $detail = & $body
    $script:results += [pscustomobject]@{ Check = $name; Result = "PASS"; Detail = $detail }
  } catch {
    $msg = $_.Exception.Message
    try { $msg = ($_.ErrorDetails.Message | ConvertFrom-Json).error } catch {}
    $script:results += [pscustomobject]@{ Check = $name; Result = "FAIL"; Detail = $msg }
  }
}

Check "health" {
  $h = Invoke-RestMethod "$Api/api/health"
  if (-not $h.db) { throw "database down" }
  "db ok, openai_key=$($h.openai_key)"
}
$tok = $null
Check "auth" {
  $script:tok = (Invoke-RestMethod -Method Post "$Api/api/auth" -ContentType "application/json" -Body (@{ passcode = $Passcode } | ConvertTo-Json)).token
  "token issued"
}
$hdr = @{ "X-Nazar-Token" = $tok }
Check "cameras" {
  $c = Invoke-RestMethod "$Api/api/cameras" -Headers $hdr
  if ($c.Count -lt 1) { throw "no cameras - run scripts/demo_setup.py" }
  "$($c.Count) cameras"
}
Check "ask (text)" {
  $body = [System.Text.Encoding]::UTF8.GetBytes((@{ text = $Question } | ConvertTo-Json))
  $r = Invoke-RestMethod -Method Post "$Api/api/ask" -Headers $hdr -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 90
  $n = if ($r.count) { " count=$($r.count.value)" } else { "" }
  "'$($r.reply_text)'$n clips=$($r.clips.Count) audio=$([bool]$r.audio_url) $([math]::Round($r.latency_ms/1000,1))s"
}
Check "rule compile + replay" {
  $body = [System.Text.Encoding]::UTF8.GetBytes((@{ text = $RuleText; camera_id = $RuleCamera } | ConvertTo-Json))
  $r = Invoke-RestMethod -Method Post "$Api/api/rules/compile" -Headers $hdr -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 90
  if (-not $r.ok) { throw "not compiled: $($r.question)" }
  Invoke-RestMethod -Method Delete "$Api/api/rules/$($r.rule_id)" -Headers $hdr | Out-Null
  "'$($r.human)' would have fired $($r.replay.count)x (draft deleted)"
}
Check "vision service (local index)" {
  $v = Invoke-RestMethod "http://127.0.0.1:8010/health"
  "tracks indexed=$($v.tracks_indexed) keyframes=$($v.keyframes_indexed) device=$($v.device)"
}
Check "visual search (words)" {
  # multipart via curl.exe (Invoke-RestMethod -Form needs PowerShell 6+)
  $raw = & curl.exe -s -X POST "$Api/api/search/visual" -H "X-Nazar-Token: $tok" -F "text=person carrying a backpack" -F "limit=5"
  $r = $raw | ConvertFrom-Json
  if ($r.hits.Count -lt 1) { throw "no hits" }
  "$($r.hits.Count) hits, top: $($r.hits[0].camera_id) $($r.hits[0].cls) sim=$($r.hits[0].sim) level=$($r.hits[0].level)"
}
Check "count receipts" {
  $q = (Invoke-RestMethod "$Api/api/count?camera_id=office-desk&event=present&from=2026-01-01T00:00:00&to=2030-01-01T00:00:00" -Headers $hdr)
  if ($q._receipts.Count -ne $q.value) { throw "receipts $($q._receipts.Count) != count $($q.value)" }
  "office-desk people=$($q.value), receipts=$($q._receipts.Count), bucket=$($q.bucket)"
}
Check "security events + digest" {
  $e = Invoke-RestMethod "$Api/api/sec-events" -Headers $hdr
  $d = Invoke-RestMethod "$Api/api/digest?voice=false" -Headers $hdr
  "$($e.Count) events; digest: $($d.text.Substring(0, [Math]::Min(80, $d.text.Length)))"
}
Check "metrics (unit costs)" {
  $m = Invoke-RestMethod "$Api/api/metrics" -Headers $hdr
  "index=Rs0, question p50=Rs$($m.unit_costs.question_p50_inr), footage=$($m.index.footage_hours) h, tracks=$($m.index.tracks)"
}
$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object Result -eq "FAIL").Count
if ($failed) { Write-Host "SMOKE: FAIL ($failed failed)" -ForegroundColor Red; exit 1 } else { Write-Host "SMOKE: PASS" -ForegroundColor Green }
