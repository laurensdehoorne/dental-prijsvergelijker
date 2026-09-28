@echo off
rem Start zonder app-venster: opent de prijsvergelijker in je browser.
cd /d "%~dp0.."
.venv\Scripts\python.exe app.py
pause
