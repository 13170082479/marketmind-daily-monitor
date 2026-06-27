@echo off
cd /d "%~dp0\.."
set "PYTHONPATH=%~dp0..\src;%PYTHONPATH%"
C:\Python314\python.exe -m marketmind_api.scripts.run_daily_market_monitor %*
