<#
.SYNOPSIS
  Play the bag clip as a LIVE camera (frames stamped with "now", looping) for live alerts without a phone.
.DESCRIPTION
  Default camera id is "live-demo" (created with the Office desk zones). Use -Camera office-desk to play it on the
  Office desk camera itself, so a rule created there ("Jab bhi koi desk 14 se bag uthaye, mujhe batana") replays on
  last night's footage AND fires live. The bag is put down ~35 s into the loop and picked up at ~110 s.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\demo_live.ps1 -Camera office-desk
#>
param(
  [string]$Camera = "live-demo",
  [string]$Clip = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Clip) {
  $staged = Join-Path $root "samples\staged_bag.mp4"
  $Clip = if (Test-Path $staged) { $staged } else { Join-Path $root "samples\clip6_bag.mp4" }
}
if (-not (Test-Path $Clip)) { throw "Clip not found: $Clip (run: python scripts\fetch_samples.py)" }
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# make sure the camera exists, with the Office desk zones/settings when it is new
$setup = @"
import sys
sys.path.insert(0, r'$root\backend')
from psycopg.types.json import Jsonb
from nazar.core import db
cam = sys.argv[1]; clip = sys.argv[2]
if not db.fetch_one('SELECT 1 FROM cameras WHERE id=%s', (cam,)):
    ref = db.fetch_one("SELECT zones, settings FROM cameras WHERE id='office-desk'") or {'zones': [], 'settings': {}}
    db.execute("INSERT INTO cameras(id, name, source_url, kind, zones, settings) VALUES (%s,%s,%s,'file',%s,%s)",
               (cam, 'Live demo (desk)', clip, Jsonb(ref['zones']), Jsonb(ref['settings'])))
    print('created camera', cam)
else:
    print('camera', cam, 'exists')
"@
$tmp = [System.IO.Path]::GetTempFileName() + ".py"
Set-Content -Path $tmp -Value $setup -Encoding utf8
& $py $tmp $Camera (Resolve-Path $Clip).Path
Remove-Item $tmp -ErrorAction SilentlyContinue

Write-Host "Starting live edge for '$Camera' from $Clip (looping, stamped with now). Ctrl+C to stop."
Push-Location (Join-Path $root "backend")
try {
  & $py -m nazar.edge.run --camera $Camera --source (Resolve-Path $Clip).Path --simulate-live --loop
} finally {
  Pop-Location
}
