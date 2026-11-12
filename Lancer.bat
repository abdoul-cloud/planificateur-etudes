@echo off
rem Lance le Planificateur d etudes (double-cliquer ce fichier).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m planificateur
