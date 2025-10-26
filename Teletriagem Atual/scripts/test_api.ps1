param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

Write-Host "===> GET /healthz" -ForegroundColor Cyan
$health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/healthz"
$health | ConvertTo-Json -Depth 4

Write-Host "===> POST /api/triage/" -ForegroundColor Cyan
$manualBody = @{ complaint = "dor no peito"; age = 50 }
$manual = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/triage/" -Body ($manualBody | ConvertTo-Json) -ContentType "application/json"
$manual | ConvertTo-Json -Depth 4

Write-Host "===> POST /api/triage/ai" -ForegroundColor Cyan
$aiBody = @{ complaint = "dor no peito há 30 minutos"; age = 50; vitals = @{ hr = 88; sbp = 130; dbp = 85; temp = 36.7; spo2 = 97 } }
$aiResponse = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/triage/ai" -Body ($aiBody | ConvertTo-Json) -ContentType "application/json"
$aiResponse | ConvertTo-Json -Depth 6
