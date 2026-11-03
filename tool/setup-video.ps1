$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path $PSScriptRoot -Parent
# Gyan's release build, linked by FFmpeg; URL/checksum recorded 2026-10-28.
$archiveUrl = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
$expectedHash = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
$runtime = Join-Path $backendRoot '.local/toolchains/ffmpeg-9.0.2'
$binary = Join-Path $runtime 'ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe'
if (-not (Test-Path -LiteralPath $binary)) {
    $archive = Join-Path $backendRoot '.local/toolchains/ffmpeg-9.0.2.zip'
    New-Item -ItemType Directory -Force -Path (Split-Path $archive -Parent) | Out-Null
    if (-not (Test-Path -LiteralPath $archive)) {
        $download = "$archive.$([guid]::NewGuid().ToString('N')).download"
        & curl.exe --fail --location --retry 2 --retry-delay 2 --connect-timeout 15 --max-time 900 --silent --show-error --output $download $archiveUrl
        if ($LASTEXITCODE -ne 0) { throw "Video tools download failed; partial file preserved at $download" }
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Video tools checksum mismatch; file preserved.' }
        Move-Item -LiteralPath $download -Destination $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Video tools checksum mismatch; no executable started.' }
    if (Test-Path -LiteralPath $runtime) { throw 'Incomplete video tools directory exists; preserved for inspection.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime
}
& $binary -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw 'Video runtime check failed.' }
Write-Host 'Project FFmpeg installed; global PATH unchanged.'
