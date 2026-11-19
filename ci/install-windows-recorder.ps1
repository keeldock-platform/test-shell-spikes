$ErrorActionPreference = 'Stop'
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    choco install ffmpeg --yes --no-progress --limit-output
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg installation failed' }
    # Chocolatey exposes shims in this existing PATH directory in this step too.
    $env:PATH = "$env:ChocolateyInstall\bin;$env:PATH"
}
# Prefer the encoder payload over Chocolatey's launcher shim when recording hashes.
if ($env:ChocolateyInstall) {
    $packageRoot = Join-Path $env:ChocolateyInstall 'lib/ffmpeg'
    $payload = Get-ChildItem $packageRoot -Filter ffmpeg.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($payload) {
        $env:PATH = "$($payload.DirectoryName);$env:PATH"
        if ($env:GITHUB_PATH) {
            [System.IO.File]::AppendAllText($env:GITHUB_PATH, $payload.DirectoryName + [Environment]::NewLine,
                [System.Text.UTF8Encoding]::new($false))
        }
    }
}
ffmpeg -version
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg probe failed' }
ffprobe -version
if ($LASTEXITCODE -ne 0) { throw 'FFprobe probe failed' }
