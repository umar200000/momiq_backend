param(
    [ValidateRange(1,65535)][int]$Port = 8080,
    [string]$DataDir,
    [switch]$Seed,
    [switch]$App,
    [string]$Device = 'emulator-5554'
)
$ErrorActionPreference = 'Stop'
$backendRoot = $PSScriptRoot
if (-not $DataDir) {
    $DataDir = Join-Path $backendRoot $(if ($Seed) { '.local/preview' } else { '.local/local' })
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$baseUrl = "http://127.0.0.1:$Port"
$pythonExe = python -c 'import sys; print(sys.executable)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
$saved = @{}
foreach ($key in @('MOMIQ_ENV','MOMIQ_DATA_DIR','MOMIQ_PORT','MOMIQ_HOST','MOMIQ_ALLOW_TEST_LOGIN')) {
    $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    $env:MOMIQ_ENV = 'local'
    $env:MOMIQ_DATA_DIR = $DataDir
    $env:MOMIQ_PORT = "$Port"
    $env:MOMIQ_HOST = '127.0.0.1'
    $env:MOMIQ_ALLOW_TEST_LOGIN = '1'
    Push-Location $backendRoot
    try {
        $instanceId = & $pythonExe -c 'import server; print(server.instance_id())'
        if ($LASTEXITCODE -ne 0) { throw 'Invalid runtime settings.' }
        $health = $null
        try { $health = Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 2 } catch {}
        if ($health -and ($health.mode -ne 'local' -or $health.instanceId -ne $instanceId)) {
            throw "Port $Port belongs to a different/older server. Use another -Port; no process was stopped."
        }
        if ($Seed) {
            & $pythonExe seed_test_data.py --data-dir $DataDir
            if ($LASTEXITCODE -ne 0) { throw 'Fixture seeding refused or failed.' }
        }
        if (-not $health) {
            New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
            $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList '-u', 'server.py' -WorkingDirectory $backendRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $DataDir 'server.log') -RedirectStandardError (Join-Path $DataDir 'server-error.log') -PassThru
            $serverProcess.Id | Set-Content (Join-Path $DataDir 'server.pid')
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                try { $health = Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 1 } catch {}
                if ($health -or $serverProcess.HasExited) { break }
                Start-Sleep -Milliseconds 200
            }
            if (-not $health -or $health.instanceId -ne $instanceId -or $health.mode -ne 'local') {
                throw "Backend did not start correctly. See $DataDir/server-error.log"
            }
        }
    } finally { Pop-Location }
} finally {
    foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
}
Write-Host "Admin: $baseUrl/admin/"
Write-Host "Credentials file: $DataDir/admin-login.txt"
if ($App) {
    $adbExe = Join-Path $env:LOCALAPPDATA 'Android/sdk/platform-tools/adb.exe'
    & $adbExe -s $Device reverse "tcp:$Port" "tcp:$Port"
    if ($LASTEXITCODE -ne 0) { throw 'Start or connect the selected Android device first.' }
    Push-Location (Join-Path (Split-Path $backendRoot -Parent) 'momiq_app')
    try {
        if (-not (Test-Path lib/core/config/maps_key.local.dart)) {
            Copy-Item lib/core/config/maps_key.example.dart lib/core/config/maps_key.local.dart
        }
        & ./tool/flutter.ps1 run --no-pub -d $Device --dart-define=MOMIQ_ENV=local "--dart-define=MOMIQ_API_URL=$baseUrl/api"
        if ($LASTEXITCODE -ne 0) { throw 'Flutter run failed.' }
    } finally { Pop-Location }
}
