$env:HTTP_PROXY  = "http://192.168.1.1:8118"
$env:HTTPS_PROXY = "http://192.168.1.1:8118"
$env:NO_PROXY    = "localhost,127.0.0.1,::1"

Write-Host "Proxy set to 192.168.1.1:8118"
Write-Host "NO_PROXY set to localhost,127.0.0.1,::1"
Write-Host ""
$maxRetries = 12
$attempt    = 0
$maxWait    = $maxRetries * 5

Write-Host "Waiting for proxy 192.168.1.1:8118 (max $maxWait seconds)..."

while ($true) {
    $result = Test-NetConnection -ComputerName 192.168.1.1 -Port 8118 -WarningAction SilentlyContinue
    if ($result.TcpTestSucceeded) {
        Write-Host "Proxy is reachable. Launching freebuff..."
        break
    }
    $attempt++
    if ($attempt -ge $maxRetries) {
        Write-Host ""
        Write-Host "ERROR: Proxy unreachable after $maxWait seconds. Aborting." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "Proxy not yet available (attempt $attempt/$maxRetries), retrying in 5 seconds..."
    Start-Sleep -Seconds 5
}

Start-Process freebuff
