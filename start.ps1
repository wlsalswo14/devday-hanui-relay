$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$hanuiUrl = 'http://127.0.0.1:8765'
$hanuiChromePaths = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
)
$hanuiChrome = $hanuiChromePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $hanuiChrome) { throw 'Google Chrome is required to open Hanui. Install Chrome and run this script again.' }
$hanuiReady = $false
python start_browser_search.py
if ($LASTEXITCODE -ne 0) { Write-Warning 'Background search unavailable; DB conversation remains available.' }
try { $hanuiReady = (Invoke-WebRequest -Uri "$hanuiUrl/api/config" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}
if (-not $hanuiReady) {
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot '.runtime') -Force | Out-Null
    $hanuiPython = (Get-Command python -CommandType Application | Select-Object -First 1).Source
    $hanuiServer = Start-Process -FilePath $hanuiPython -ArgumentList '-X','utf8','server.py','--port','8765' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime/server.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime/server.stderr.log')
    for ($hanuiAttempt = 0; $hanuiAttempt -lt 40; $hanuiAttempt++) {
        try { $hanuiReady = (Invoke-WebRequest -Uri "$hanuiUrl/api/config" -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200 } catch {}
        if ($hanuiReady) { break }
        if ($hanuiServer.HasExited) { throw 'Hanui server exited. Check .runtime/server.stderr.log.' }
        Start-Sleep -Milliseconds 250
    }
    if (-not $hanuiReady) { throw 'Hanui server did not become ready.' }
    $hanuiServer.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot '.runtime/server.pid')
}
Start-Process -FilePath $hanuiChrome -ArgumentList '--new-tab',$hanuiUrl
Write-Output "Hanui opened in Chrome: $hanuiUrl"
