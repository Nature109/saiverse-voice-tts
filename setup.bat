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
echo [1/7] Installing pack-level Python packages...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install -r requirements.txt
if errorlevel 1 goto :err
echo [OK]

REM --- 2. Backend install (clone + weights + requirements) ------------------
echo.
echo [2/7] Running install_backends.py for !BACKEND!...
python scripts\install_backends.py !BACKEND!
if errorlevel 1 goto :err
echo [OK]

REM --- NLTK data (GPT-SoVITS が英語テキスト処理に必要) ---------------------
echo.
echo [3/7] Downloading NLTK data...
python -c "import nltk; nltk.download('averaged_perceptron_tagger_eng', quiet=True); nltk.download('cmudict', quiet=True); print('OK')"

REM --- 3. Verify CUDA torch -------------------------------------------------
REM GPT-SoVITS の requirements.txt が CPU 版 torch を上書きインストールする
REM ことがあるため、Step 2 の後に必ず CUDA 版を確認・再導入する。
echo.
echo [4/7] Verifying CUDA availability...
python -c "import torch; print('torch', torch.__version__, 'CUDA:', torch.cuda.is_available())"
python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 (
    echo.
    echo [INFO] CUDA not available. Reinstalling CUDA-enabled torch...
    REM cu128 は Python 3.13+ をサポート。cu121 は 3.12 以下のみ。
    REM cu128 を先に試し、失敗したら cu121 にフォールバック。
    python -m pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu128 --force-reinstall 2>nul
    if errorlevel 1 (
        echo [INFO] cu128 not available for this Python version, trying cu121...
        python -m pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --force-reinstall
    )
    echo.
    echo [INFO] Verifying CUDA after reinstall...
    python -c "import torch; print('torch', torch.__version__, 'CUDA:', torch.cuda.is_available())"
    python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
    if errorlevel 1 (
        echo.
        echo [WARN] CUDA is still not available after reinstall.
        echo        GPU acceleration will not work. Possible causes:
        echo          - NVIDIA GPU driver is not installed ^(run nvidia-smi to check^)
        echo          - No NVIDIA GPU in this machine
        echo          - CUDA toolkit version mismatch
        echo        TTS will run on CPU ^(very slow, not recommended^).
    ) else (
        echo [OK] CUDA restored successfully
    )
) else (
    echo [OK] CUDA available
)

REM --- 4. Import playbooks to DB -------------------------------------------
echo.
echo [5/7] Importing playbooks to database...
pushd "%SAIVERSE_ROOT%"
python scripts\import_all_playbooks.py --force
if errorlevel 1 (
    echo [WARN] Playbook import failed. TTS may not work until playbooks are imported.
) else (
    echo [OK] Playbooks imported ^(sub_speak with tts_speak node^)
)
popd

REM --- 5. sounddevice smoke test --------------------------------------------
echo.
echo [6/7] Checking sounddevice output devices...
python -c "import sounddevice as sd; print(sd.query_devices())"
if errorlevel 1 goto :err
echo [OK]

REM --- 6. Reference audio check ---------------------------------------------
echo.
echo [7/7] Checking voice profile...
if not exist "voice_profiles\samples\_default" (
    mkdir "voice_profiles\samples\_default"
    echo [INFO] Created voice_profiles\samples\_default directory
)
if not exist "voice_profiles\samples\_default\ref.wav" (
    echo [WARN] voice_profiles\samples\_default\ref.wav not found.
    echo        Place a Japanese reference wav file ^(3-10s, 16kHz+ mono^) there and
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
