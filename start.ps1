Set-Location $PSScriptRoot
try {
  $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 2
  if ($health.ok) { Write-Host 'Momiq ishlayapti: http://127.0.0.1:8080/admin/'; exit 0 }
} catch { }
python server.py
