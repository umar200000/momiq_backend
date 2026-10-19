$adbPath = Join-Path $env:LOCALAPPDATA 'Android/Sdk/platform-tools/adb.exe'
if (!(Test-Path -LiteralPath $adbPath)) { throw 'Android SDK adb.exe topilmadi' }
& $adbPath devices
& $adbPath reverse tcp:8080 tcp:8080
if ($LASTEXITCODE -ne 0) { throw 'Telefonni USB orqali ulang va USB debugging ruxsatini bering.' }
Write-Host 'Telefon backendga ulandi: http://127.0.0.1:8080'
