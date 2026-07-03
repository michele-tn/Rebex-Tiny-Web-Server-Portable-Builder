@echo off
setlocal
cd /d "%~dp0.."
if not exist "dist\build_tiny_web_server_portable.exe" (
  echo ERROR: dist\build_tiny_web_server_portable.exe not found.
  pause
  exit /b 1
)
"dist\build_tiny_web_server_portable.exe" --output-dir "RebexTinyWebServer_Portable_Production" --force --import-root-ca
pause
endlocal
