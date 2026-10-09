@echo off
cd /d "%~dp0"
python -m pip install --target .deps -r requirements.txt
pause
