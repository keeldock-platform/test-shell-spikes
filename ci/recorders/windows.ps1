param(
  [Parameter(Mandatory = $true)][ValidateSet("start", "stop")][string]$Action,
  [Parameter(Mandatory = $true)][string]$Output
)
$ErrorActionPreference = "Stop"
$pidFile = [System.IO.Path]::ChangeExtension($Output, ".pid")
$logFile = [System.IO.Path]::ChangeExtension($Output, ".log")
if ($Action -eq "start") {
  $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if (-not $ffmpeg) { throw "ffmpeg is unavailable" }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
  $arguments = @("-copyts", "-nostdin", "-hide_banner", "-loglevel", "warning", "-y", "-f", "gdigrab", "-framerate", "60", "-draw_mouse", "1", "-use_wallclock_as_timestamps", "1", "-i", "desktop", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-f", "matroska", $Output)
  $process = Start-Process -FilePath $ffmpeg.Source -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardError $logFile -RedirectStandardOutput "$logFile.out"
  Set-Content -NoNewline -Path $pidFile -Value $process.Id
  Start-Sleep -Seconds 2
  if ($process.HasExited) { throw "ffmpeg exited during capture preflight" }
} else {
  if (Test-Path $pidFile) {
    $recorderPid = [int](Get-Content -Raw $pidFile)
    $ownedRecorder = Get-Process -Id $recorderPid -ErrorAction SilentlyContinue
    if ($ownedRecorder -and -not $ownedRecorder.HasExited) {
      $ownedRecorder.Kill()
      if (-not $ownedRecorder.WaitForExit(10000)) { throw "Recorder did not stop before hash finalization" }
    }
    Remove-Item -Force $pidFile
  }
}
