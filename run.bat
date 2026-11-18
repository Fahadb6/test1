@echo off
cd /d "%~dp0"
py -3 manage.py init-db
if errorlevel 1 exit /b 1
py -3 manage.py check
if errorlevel 1 exit /b 1
py -3 server.py
