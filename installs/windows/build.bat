@echo off
setlocal EnableExtensions

cd /d "%~dp0\..\.."
set "CLIENT_ROOT=%CD%"
set "PLATFORM_ROOT=%CLIENT_ROOT%\installs\windows"
set "PYTHONPATH=%CLIENT_ROOT%\src"

python "%CLIENT_ROOT%\scripts\check_source_secrets.py"
if errorlevel 1 exit /b 1

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo ERROR: PyInstaller is not available in this Python environment.
    echo Install the packages listed in client\requirements.txt, then retry.
    exit /b 1
)

for /f "delims=" %%V in ('python -c "import fsociety_client; print(fsociety_client.__version__)"') do set "FSOCIETY_VERSION=%%V"
if not defined FSOCIETY_VERSION (
    echo ERROR: Could not read the fsociety client version.
    exit /b 1
)

set "PACKAGE_NAME=fsociety-open-beta-v%FSOCIETY_VERSION%-windows-x64"
set "PACKAGE_DIR=%PLATFORM_ROOT%\dist\%PACKAGE_NAME%"
set "ZIP_PATH=%PLATFORM_ROOT%\dist\%PACKAGE_NAME%.zip"

echo Building fsociety Open Beta v%FSOCIETY_VERSION% for Windows...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name fsociety ^
    --icon "%CLIENT_ROOT%\assets\fsociety.ico" ^
    --add-data "%CLIENT_ROOT%\assets;assets" ^
    --paths "%CLIENT_ROOT%\src" ^
    --collect-all nostr_sdk ^
    --hidden-import PyQt6.QtMultimedia ^
    --hidden-import PyQt6.QtMultimediaWidgets ^
    --distpath "%PLATFORM_ROOT%\pyinstaller-dist" ^
    --workpath "%PLATFORM_ROOT%\build" ^
    --specpath "%PLATFORM_ROOT%\build" ^
    "%CLIENT_ROOT%\main.py"
if errorlevel 1 exit /b 1

if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
mkdir "%PACKAGE_DIR%"
copy /y "%PLATFORM_ROOT%\pyinstaller-dist\fsociety.exe" "%PACKAGE_DIR%\fsociety.exe" >nul
copy /y "%PLATFORM_ROOT%\PACKAGE_README.txt" "%PACKAGE_DIR%\README.txt" >nul

powershell -NoProfile -Command "$h=(Get-FileHash -Algorithm SHA256 -LiteralPath '%PACKAGE_DIR%\fsociety.exe').Hash.ToLower(); Set-Content -Encoding ascii -LiteralPath '%PACKAGE_DIR%\SHA256SUMS.txt' -Value ($h + '  fsociety.exe')"
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
powershell -NoProfile -Command "Compress-Archive -CompressionLevel Optimal -LiteralPath '%PACKAGE_DIR%' -DestinationPath '%ZIP_PATH%'"
if errorlevel 1 exit /b 1

echo.
echo Build complete:
echo   %ZIP_PATH%
exit /b 0
