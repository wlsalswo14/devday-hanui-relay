$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python start_browser_search.py
if ($LASTEXITCODE -ne 0) { Write-Warning 'Background search unavailable; DB conversation remains available.' }
python server.py --port 8765
