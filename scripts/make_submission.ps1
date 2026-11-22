<#
.SYNOPSIS
  Build the clean submission zip: every committed file (git archive: no node_modules, .venv, web/out, data/, .env) +
  the demo clips in samples/ (incl. hackathon.mp4) + the demo film + a .env that contains ONLY a budget-capped test key.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make_submission.ps1 -TestKey sk-proj-...
  (no -TestKey: the zip has no .env; reviewers paste their own key into .env from .env.example)
#>
param([string]$TestKey = "", [string]$Out = "nazar_submission.zip")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$stage = Join-Path $env:TEMP "nazar_submission"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory $stage | Out-Null
git archive --format=zip -o (Join-Path $stage "code.zip") HEAD
Expand-Archive (Join-Path $stage "code.zip") -DestinationPath (Join-Path $stage "Nazar")
Remove-Item (Join-Path $stage "code.zip")
$dst = Join-Path $stage "Nazar"
foreach ($f in "clip1", "clip2", "clip3", "clip4", "clip5", "clip6_bag", "hackathon") {
  $p = Join-Path $root "samples\$f.mp4"
  if (Test-Path $p) { Copy-Item $p (Join-Path $dst "samples\$f.mp4") }
}
if (Test-Path "$root\demo\nazar_film.mp4") { Copy-Item "$root\demo\nazar_film.mp4" (Join-Path $dst "nazar_film.mp4") }
if ($TestKey) {
  (Get-Content "$root\.env.example") -replace '^OPENAI_API_KEY=.*', "OPENAI_API_KEY=$TestKey" | Set-Content (Join-Path $dst ".env") -Encoding utf8
}
# zip with forward slashes (Compress-Archive on Windows PowerShell 5 writes backslashes)
$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -c "import os,sys,zipfile; s,o=sys.argv[1],sys.argv[2]; z=zipfile.ZipFile(o,'w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(r,f), os.path.relpath(os.path.join(r,f), os.path.dirname(s)).replace(os.sep,'/')) for r,_,fs in os.walk(s) for f in fs]; z.close()" $dst (Join-Path $root $Out)
$mb = [math]::Round((Get-Item (Join-Path $root $Out)).Length / 1MB, 1)
Write-Host "wrote $Out ($mb MB): code + samples + film$(if ($TestKey) {' + .env with the test key'})"
