<#
.SYNOPSIS
  Stream a video file in a loop into MediaMTX over RTSP, so the REAL live path (RTSP -> edge) runs without a camera.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\live_from_file.ps1 samples\clip2.mp4 cam1
  # then add camera "cam1" with source rtsp://localhost:8554/cam1 (Cameras -> Add -> CCTV/RTSP) or:
  python -m nazar.edge.run --camera cam1 --source rtsp://localhost:8554/cam1
#>
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$Clip,
  [Parameter(Mandatory = $true, Position = 1)][string]$CameraId,
  [string]$Host_ = "localhost",
  [int]$Port = 8554
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Clip)) { throw "Clip not found: $Clip" }

function Find-Ffmpeg {
  $c = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($scope in "User", "Machine") {
    foreach ($d in ([Environment]::GetEnvironmentVariable("Path", $scope) -split ";")) {
      if ($d -and (Test-Path (Join-Path $d "ffmpeg.exe"))) { return (Join-Path $d "ffmpeg.exe") }
    }
  }
  throw "ffmpeg not found on PATH"
}

$ff = Find-Ffmpeg
$url = "rtsp://${Host_}:$Port/$CameraId"
Write-Host "Streaming $Clip -> $url (loop, real-time). Ctrl+C to stop."
# Re-encode with short GOPs so a newly connected reader gets a keyframe quickly.
& $ff -hide_banner -loglevel warning -re -stream_loop -1 -i $Clip -an `
  -c:v libx264 -preset veryfast -tune zerolatency -g 30 -pix_fmt yuv420p `
  -f rtsp -rtsp_transport tcp $url
