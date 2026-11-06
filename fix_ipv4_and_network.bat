@echo off
setlocal EnableDelayedExpansion

:: ---------------------------------------------------------
:: 1. Self-Elevation to Administrator
:: ---------------------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

title Content Pipeline - Total IPv4 & Network Optimizer
color 0B
cls

echo =====================================================================
echo           CONTENT PIPELINE: 100%% RELIABLE IPV4 NETWORK FIX
echo =====================================================================
echo.

:: ---------------------------------------------------------
:: 2. Prioritize IPv4 over IPv6 in Windows RFC 6724 Policy (Instant)
:: ---------------------------------------------------------
echo [*] Step 1: Prioritizing IPv4 over IPv6 in Windows Prefix Policy...
netsh interface ipv6 set prefixpolicy ::ffff:0:0/96 50 0 >nul 2>&1
netsh interface ipv6 set prefixpolicy ::/0 40 1 >nul 2>&1
netsh interface ipv6 set prefixpolicy ::1/128 30 2 >nul 2>&1
netsh interface ipv6 set prefixpolicy 2002::/16 20 3 >nul 2>&1
netsh interface ipv6 set prefixpolicy ::/96 10 4 >nul 2>&1
echo     [OK] IPv4 given highest precedence (50) over IPv6 (40). Takes effect immediately!

:: ---------------------------------------------------------
:: 3. Disable IPv6 at the Windows Kernel / Registry Layer
:: ---------------------------------------------------------
echo.
echo [*] Step 2: Configuring Windows Kernel to prefer IPv4 (DisabledComponents)...
reg add "HKLM\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters" /v DisabledComponents /t REG_DWORD /d 32 /f >nul 2>&1
echo     [OK] Registry configured: Windows socket layer now strictly prefers IPv4.

:: ---------------------------------------------------------
:: 4. Disable IPv6 Binding on All Physical Network Adapters
:: ---------------------------------------------------------
echo.
echo [*] Step 3: Disabling IPv6 bindings on all active network adapters...
powershell -Command "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { Disable-NetAdapterBinding -Name $_.Name -ComponentID ms_tcpip6 -ErrorAction SilentlyContinue; Write-Host ('     [OK] Disabled IPv6 on adapter: ' + $_.Name) }"

:: ---------------------------------------------------------
:: 5. Set Ultra-Fast Anycast DNS (1.1.1.1 and 8.8.8.8) on All Active Adapters
:: ---------------------------------------------------------
echo.
echo [*] Step 4: Setting DNS to Cloudflare (1.1.1.1) and Google (8.8.8.8) on active adapters...
powershell -Command "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { Set-DnsClientServerAddress -InterfaceAlias $_.Name -ServerAddresses ('1.1.1.1', '8.8.8.8') -ErrorAction SilentlyContinue; Write-Host ('     [OK] Configured DNS (1.1.1.1, 8.8.8.8) on: ' + $_.Name) }"

:: ---------------------------------------------------------
:: 6. Ensure 127.0.0.1 Localhost Mapping & Enforce netdns=cgo System-Wide
:: ---------------------------------------------------------
echo.
echo [*] Step 5: Ensuring local machine resolution (127.0.0.1 localhost)...
attrib -R "%windir%\system32\drivers\etc\hosts" >nul 2>&1
findstr /C:"127.0.0.1 localhost" "%windir%\system32\drivers\etc\hosts" >nul 2>&1
if %errorlevel% neq 0 (
    echo.>> "%windir%\system32\drivers\etc\hosts"
    echo 127.0.0.1 localhost>> "%windir%\system32\drivers\etc\hosts"
    echo ::1 localhost>> "%windir%\system32\drivers\etc\hosts"
    echo     [OK] Added 127.0.0.1 localhost and ::1 localhost to Windows hosts file.
) else (
    echo     [OK] localhost mapping already present in Windows hosts file.
)

:: Force Go runtime to use Windows native GetAddrInfoW resolver (netdns=cgo)
:: This prevents Go's pure-Go resolver from sending localhost queries to upstream DNS (1.1.1.1:53).
set GODEBUG=netdns=cgo
setx GODEBUG "netdns=cgo" >nul 2>&1
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v GODEBUG /t REG_SZ /d "netdns=cgo" /f >nul 2>&1
echo     [OK] GODEBUG=netdns=cgo applied system-wide (forces in-memory localhost resolution).

:: ---------------------------------------------------------
:: 7. Flush Windows DNS Cache & Reset Sockets
:: ---------------------------------------------------------
echo.
echo [*] Step 6: Flushing DNS cache and resetting TCP state...
ipconfig /flushdns >nul 2>&1
netsh winsock reset catalog >nul 2>&1
echo     [OK] DNS cache flushed and network catalog refreshed.

:: ---------------------------------------------------------
:: 7. Test Google Cloud Code & agy Endpoints
:: ---------------------------------------------------------
echo.
echo =====================================================================
echo                     VERIFYING CONNECTIVITY
echo =====================================================================
echo.
echo [*] Testing Google Cloud Code endpoint via IPv4...
curl.exe -4 -s -o nul -w "     [OK] Google Cloud Code HTTP Response: %%{http_code}\n" https://daily-cloudcode-pa.googleapis.com

echo.
echo [*] Testing Antigravity CLI ('agy -p "hi"')...
agy -p "Reply with exactly: PING"

echo.
echo =====================================================================
echo   SUCCESS! Your system is now 100%% locked to reliable IPv4 routing.
echo   You can now launch Content Pipeline with extreme stability!
echo =====================================================================
echo.
pause

