Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = "$(Join-Path $PSScriptRoot '..\src');$env:PYTHONPATH"
& "C:\Python314\python.exe" -m marketmind_api.scripts.run_daily_market_monitor @args
