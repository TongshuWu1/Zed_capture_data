@echo off
cd /d "%~dp0"
py -3.11 run.py
if errorlevel 1 pause
