@echo off
setlocal
cd /d "%~dp0.."
py -3 -m pip install -r requirements.txt
py -3 "src\build_tiny_web_server_portable.py" --output-dir "RebexTinyWebServer_Portable_Production" --force --import-root-ca
pause
endlocal
