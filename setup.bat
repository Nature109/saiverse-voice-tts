@echo off
REM ===========================================================================
REM  saiverse-voice-tts setup script (Windows)
REM
REM  Usage:
REM    setup.bat                   - install the default backend (gpt_sovits)
REM    setup.bat gpt_sovits        - install GPT-SoVITS only
REM    setup.bat irodori           - install Irodori-TTS (experimental)
REM    setup.bat all               - install all supported backends
REM
REM  This script:
REM    1. Activates SAIVerse's .venv
REM    2. Installs pack-level Python deps (sounddevice etc)
REM    3. Runs install_backends.py (clones upstream + pip install + weights DL)
REM    4. Verifies torch is CUDA-enabled (reinstalls cu121 wheel if not)
REM    5. Prints next-step instructions
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================================================
echo  saiverse-voice-tts setup
echo ==========================================================================
echo.

REM --- Resolve SAIVerse root (pack is at <root>/expansion_data/<pack>/) -----
set "PACK_ROOT=%~dp0"
if "%PACK_ROOT:~-1%"=="\" set "PACK_ROOT=%PACK_ROOT:~0,-1%"
for %%I in ("%PACK_ROOT%\..\..") do set "SAIVERSE_ROOT=%%~fI"
set "VENV_ACTIVATE=%SAIVERSE_ROOT%\.venv\Scripts\activate.bat"

echo [INFO] Pack root    : %PACK_ROOT%
echo [INFO] SAIVerse root: %SAIVERSE_ROOT%

if not exist "%VENV_ACTIVATE%" (
    echo.
    echo [ERROR] SAIVerse virtual environment not found at:
    echo         %VENV_ACTIVATE%
    echo         Run SAIVerse's own setup.bat first.
    pause
    exit /b 1
)
call "%VENV_ACTIVATE%"
echo [OK] venv activated

REM --- MSVC UTF-8 workaround -----------------------------------------------
REM Windows + CP932 環境で C/C++ 拡張のソースビルド時に非 ASCII 文字で
REM コンパイルエラーになる問題を回避 (editdistance, opencc 等)。
set "CL=/utf-8"

REM --- Backend selection ----------------------------------------------------
set "BACKEND=%~1"
if "!BACKEND!"=="" set "BACKEND=gpt_sovits"
echo [INFO] Target backend(s): !BACKEND!

REM --- 1. Pack-level Python packages ----------------------------------------
echo.
echo [1/5] Installing pack-level Python packages...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install -r requirements.txt
if errorlevel 1 goto :err
echo [OK]

REM --- 2. Backend install (clone + weights + requirements) ------------------
echo.
echo [2/5] Running install_backends.py for !BACKEND!...
python scripts\install_backends.py !BACKEND!
if errorlevel 1 goto :err
echo [OK]

REM --- 3. Verify CUDA torch -------------------------------------------------
echo.
echo [3/5] Verifying CUDA availability...
python -c "import torch; print('torch', torch.__version__, 'CUDA:', torch.cuda.is_available())"
python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 (
    echo.
    echo [WARN] CUDA not available. Reinstalling CUDA-enabled torch cu121...
    python -m pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --force-reinstall
    python -c "import torch; print('torch', torch.__version__, 'CUDA:', torch.cuda.is_available())"
)
echo [OK]

REM --- 4. sounddevice smoke test --------------------------------------------
echo.
echo [4/5] Checking sounddevice output devices...
python -c "import sounddevice as sd; print(sd.query_devices())"
if errorlevel 1 goto :err
echo [OK]

REM --- 5. Reference audio check ---------------------------------------------
echo.
echo [5/5] Checking voice profile...
if not exist "voice_profiles\samples\_default\ref.wav" (
    echo [WARN] voice_profiles\samples\_default\ref.wav not found.
    echo        Place a Japanese reference wav file ^(3s+, 16kHz+ mono^) there and
    echo        update voice_profiles\registry.json with a matching transcription.
) else (
    echo [OK] _default ref.wav found.
)

echo.
echo ==========================================================================
echo  Setup complete!
echo ==========================================================================
echo.
echo Next steps:
echo   1. If the [WARN] above was shown, place a reference wav and edit
echo      voice_profiles\registry.json ^(ref_text must match the wav^).
echo   2. Start SAIVerse from its own root:
echo        cd /d "%SAIVERSE_ROOT%"
echo        .venv\Scripts\activate
echo        python main.py city_a
echo   3. Talk to a persona in the browser ^(http://localhost:3000^).
echo      The first utterance triggers backend model load and takes tens of
echo      seconds. Subsequent ones start speaking within about 5 seconds.
echo.
pause
exit /b 0

:err
echo.
echo [ERROR] Setup failed. See the output above for details.
pause
exit /b 1
