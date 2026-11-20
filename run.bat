@echo off
rem PromoFinder launcher for Windows.
rem   run.bat                 start the web app and open it in your browser
rem   run.bat cli run X.zip   run the command-line tool
rem   run.bat test            run the automated tests
rem   run.bat check           check the environment
rem   run.bat reset           delete .venv so the next launch rebuilds it
rem First launch creates .venv and installs dependencies; later launches start immediately.
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
rem PromoFinder reads .env itself; stop Flask asking for python-dotenv
set "FLASK_SKIP_DOTENV=1"

if /i "%~1"=="reset" (
  if exist .venv rmdir /s /q .venv
  echo Removed .venv. Run run.bat to rebuild it.
  goto :eof
)

rem ---- 1. find Python 3.10+ (the py launcher first; "python" may be the Microsoft Store stub)
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

rem ---- 2. private environment (rebuilt if missing, broken, or made on another computer)
set "VPY=.venv\Scripts\python.exe"
if exist "%VPY%" (
  "%VPY%" -c "import sys" >nul 2>nul
  if errorlevel 1 (
    echo Rebuilding .venv - it was created for another computer or is damaged.
    rmdir /s /q .venv
  )
)
if not exist "%VPY%" (
  if exist .venv rmdir /s /q .venv
  echo First launch: creating a private Python environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :novenv
)

rem ---- 3. dependencies, only when requirements.txt changed
rem (written via a file: cmd strips the quotes around a quoted program path inside for /f)
"%VPY%" -c "import hashlib;print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())" > .venv\.requirements.now 2>nul
set "HASH="
if exist .venv\.requirements.now set /p HASH=<.venv\.requirements.now
if not defined HASH set "HASH=unknown"
set "OLD="
if exist .venv\.requirements.sha256 set /p OLD=<.venv\.requirements.sha256
if not "%HASH%"=="%OLD%" (
  echo Installing dependencies - one time, needs internet...
  "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip >nul 2>nul
  "%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 goto :nodeps
  >.venv\.requirements.sha256 echo %HASH%
)
"%VPY%" -c "import flask, numpy, scipy, sklearn, yaml, vaderSentiment" >nul 2>nul
if errorlevel 1 (
  del /q .venv\.requirements.sha256 >nul 2>nul
  goto :nodeps
)

rem ---- 4. local settings for optional API keys
if not exist .env (
  copy /y .env.example .env >nul
  echo Created .env - optional API keys go there; it never leaves this computer.
)

if /i "%~1"=="check" (
  "%VPY%" -c "import promofinder, sys; print('PromoFinder', promofinder.__version__, 'ready on Python', sys.version.split()[0])"
  "%VPY%" -c "from promofinder.llm import load_dotenv, llm_status; from promofinder.config import load_config; load_dotenv(); print('LLM:', llm_status(load_config('config.yaml'))['message'])"
  goto :eof
)
if /i "%~1"=="test" (
  "%VPY%" -m pip install --disable-pip-version-check -q pytest >nul 2>nul
  "%VPY%" -m pytest -q tests
  goto :eof
)
if /i "%~1"=="cli" (
  shift
  goto :cli
)

rem ---- 5. start the web app and open the browser
if not defined PROMOFINDER_OPEN_BROWSER set "PROMOFINDER_OPEN_BROWSER=1"
"%VPY%" app.py
if errorlevel 1 pause
goto :eof

:cli
set "ARGS="
:collect
if "%~1"=="" goto :runcli
set ARGS=%ARGS% "%~1"
shift
goto :collect
:runcli
"%VPY%" -m promofinder %ARGS%
goto :eof

:nopython
echo.
echo PromoFinder could not start: Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then double-click run.bat again.
pause
exit /b 1

:novenv
echo.
echo PromoFinder could not start: creating the virtual environment failed.
echo Reinstall Python from https://www.python.org/downloads/ then run run.bat again.
pause
exit /b 1

:nodeps
echo.
echo PromoFinder could not start: installing dependencies failed (see messages above).
echo Check your internet connection and run run.bat again. To start over: run.bat reset
pause
exit /b 1
