@echo off
setlocal EnableDelayedExpansion
color 0B
cls
echo ======================================================
echo         SIMPLIFIED BANK STATEMENT PROCESSOR
echo ======================================================
echo.

REM Check if Python is installed
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Python is not installed or not in PATH.
    echo        Please install Python and try again.
    pause
    exit /b 1
)

set "SCRIPT_PATH=%~dp0Arctaris rename_statements.py"

REM Check if script exists
if not exist "%SCRIPT_PATH%" (
    color 0C
    echo ERROR: Cannot find script at "%SCRIPT_PATH%"
    echo        Please ensure the script is in the correct location.
    pause
    exit /b 1
)

REM Create temporary output file
set "TEMP_OUTPUT=%TEMP%\bank_processor_output.txt"

echo Please select an option:
echo.
echo  [1] Process files (make actual changes)
echo  [2] Preview mode (show changes without making them)
echo.

set /p OPTION="Enter your choice (1 or 2): "
echo.

if "%OPTION%"=="1" (
    echo Running in PROCESSING mode...
    python "%SCRIPT_PATH%" > "%TEMP_OUTPUT%" 2>&1
    set EXIT_CODE=%ERRORLEVEL%
) else if "%OPTION%"=="2" (
    echo Running in PREVIEW mode...
    python "%SCRIPT_PATH%" --dry-run --show-preview > "%TEMP_OUTPUT%" 2>&1
    set EXIT_CODE=%ERRORLEVEL%
) else (
    echo ERROR: Invalid option selected. Please choose 1 or 2.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo                   RESULTS
echo ======================================================
echo.

REM Display the Python script output
type "%TEMP_OUTPUT%"

echo.
echo ======================================================
echo Script completed with exit code: %EXIT_CODE%
echo Press any key to exit...
pause > nul

del "%TEMP_OUTPUT%" 2>nul 