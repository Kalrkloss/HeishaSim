@echo off
set HTTP_PROXY=http://192.0.0.4:8080
set HTTPS_PROXY=http://192.0.0.4:8080
set NO_PROXY=localhost,127.0.0.1,::1
echo Proxy set to 192.0.0.4:8080
echo NO_PROXY set to localhost,127.0.0.1,::1
echo.
set MAX_RETRIES=12
set RETRY_COUNT=0
set /a MAX_WAIT=MAX_RETRIES * 5
echo Waiting for proxy 192.0.0.4:8080 (max %MAX_WAIT% seconds)...

:wait_loop
powershell -NoProfile -Command "(Test-NetConnection -ComputerName 192.0.0.4 -Port 8080 -WarningAction SilentlyContinue).TcpTestSucceeded" | findstr /i "True" >nul 2>&1
if %errorlevel% equ 0 goto proxy_ready

set /a RETRY_COUNT+=1
if %RETRY_COUNT% geq %MAX_RETRIES% (
    echo.
    echo ERROR: Proxy unreachable after %MAX_WAIT% seconds. Aborting.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo Proxy not yet available ^(attempt %RETRY_COUNT%/%MAX_RETRIES%^), retrying in 5 seconds...
timeout /t 5 /nobreak >nul
goto wait_loop

:proxy_ready
echo Proxy is reachable. Launching freebuff...
start "" freebuff
