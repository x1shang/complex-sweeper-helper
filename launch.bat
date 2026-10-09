@echo off
cd /d "%~dp0"
python -m cshelper.gui
if errorlevel 1 pause
