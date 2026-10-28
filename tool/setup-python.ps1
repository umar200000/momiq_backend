$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $backendRoot '.local/toolchains/python-3.12'
if (-not (Test-Path -LiteralPath $runtime)) {
    py install --target=$runtime 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python runtime installation failed.' }
}
$interpreter = Join-Path $runtime 'python.exe'
& $interpreter -c 'import sys; assert sys.version_info[:2] == (3,12)'
if ($LASTEXITCODE -ne 0) { throw 'Expected Python 3.12.' }
$venv = Join-Path $backendRoot '.venv'
if (-not (Test-Path -LiteralPath $venv)) {
    & $interpreter -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& (Join-Path $venv 'Scripts/python.exe') -m pip install --require-hashes -r (Join-Path $backendRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Use ./.venv/Scripts/python.exe. Global Python was not changed.'
