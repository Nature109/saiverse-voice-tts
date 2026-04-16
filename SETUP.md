# SETUP

## クイックスタート(Windows)

前提: **SAIVerse 本体のセットアップ(`.venv` 作成まで)が完了していること**

```batch
cd %USERPROFILE%\SAIVerse\expansion_data
git clone https://github.com/Nature109/saiverse-voice-tts.git
cd saiverse-voice-tts
setup.bat
```

`setup.bat` は全自動で以下を実行します:

| ステップ | 内容 |
|---|---|
| 1/5 | パック依存(numpy, sounddevice, soundfile, huggingface_hub)を SAIVerse の `.venv` にインストール |
| 2/5 | `scripts/install_backends.py` 呼び出し — GPT-SoVITS を clone、上流 requirements.txt から `opencc` を自動除外、`opencc-python-reimplemented` 代替導入、重み(約4GB)を HuggingFace から DL、`fast_langdetect` キャッシュディレクトリ作成 |
| 3/5 | `torch.cuda.is_available()` を確認し、CPU 版 torch が入っていれば `cu121` の CUDA 版を強制再導入 |
| 4/5 | `sounddevice.query_devices()` で出力デバイスを列挙(音を鳴らすデバイスの選択用) |
| 5/5 | `voice_profiles/samples/_default/ref.wav` の有無を確認 |

所要時間: GPU環境で 5〜15分(重みDL律速)。

### セットアップ完了後の手動作業

#### 1. 参照音声の配置

```
voice_profiles/samples/_default/ref.wav
```
- 3秒以上、16kHz以上、mono、日本語の肉声
- 話速・感情が落ち着いていて背景雑音の無いクリップを推奨

#### 2. 参照テキスト(書き起こし)の調整

`voice_profiles/registry.json` を開き、`_default.ref_text` を配置した wav の**正確な**書き起こしに差し替え。句読点まで含めて合わせると品質が向上します。

#### 3. 出力デバイスの指定(必要時)

`setup.bat` の [4/5] でデバイス一覧が表示されます。`<` マークが既定出力。既定出力でない別デバイスに音を流したい場合は `config/default.json` の `output_device` に番号を指定。

```json
{
    "output_device": 7   // 例: Realtek HD Audio output
}
```

#### 4. SAIVerse 起動

```batch
cd %USERPROFILE%\SAIVerse
.venv\Scripts\activate
python main.py city_a
```

別ターミナルで Next.js フロント:
```batch
cd %USERPROFILE%\SAIVerse\frontend
npm run dev
```

ブラウザで `http://localhost:3000` → 適当なペルソナに話しかけると音声が鳴ります。

## 詳細セットアップ(手動)

`setup.bat` が動かない場合や、中身を理解したい場合の手順。

### 前提確認

```batch
cd %USERPROFILE%\SAIVerse
.venv\Scripts\activate
python --version
where python
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

- Python 3.10+
- `.venv\Scripts\python.exe` がヒットすること
- `torch.cuda.is_available()` が `True`(False なら後述「CUDA トラブル」参照)

### 1. パック依存をインストール

```batch
cd %USERPROFILE%\SAIVerse\expansion_data\saiverse-voice-tts
python -m pip install -r requirements.txt
```

### 2. GPT-SoVITS の clone + 重み DL + 依存

```batch
python scripts\install_backends.py gpt_sovits
```

内部では:
- `external/GPT-SoVITS/` へ shallow clone
- `opencc-python-reimplemented` を pip install
- `external/GPT-SoVITS/requirements.txt` から `opencc` 関連行を自動コメントアウト
- 残りを `pip install -r`
- `lj1995/GPT-SoVITS` の重みを `external/GPT-SoVITS/GPT_SoVITS/pretrained_models/` に配置
- `fast_langdetect/` サブディレクトリ作成

### 3. CUDA 版 torch の確認

```batch
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
```

`True` でなければ:
```batch
pip uninstall -y torch torchaudio torchvision
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121
```

### 4. 単体ロード確認

```batch
python -c "import sys, os; sys.path.insert(0, r'%CD%\external\GPT-SoVITS'); sys.path.insert(0, r'%CD%\external\GPT-SoVITS\GPT_SoVITS'); os.chdir(r'%CD%\external\GPT-SoVITS'); from TTS_infer_pack.TTS import TTS, TTS_Config; TTS(TTS_Config('GPT_SoVITS/configs/tts_infer.yaml')); print('OK')"
```
`Loading Text2Semantic weights ...` 〜 `OK` まで流れれば成功。

### 5. 参照音声配置・registry 編集

上記「セットアップ完了後の手動作業」と同じ。

## トラブルシューティング

### opencc のビルドエラー

```
error: Building wheel for opencc ... [WinError 5] アクセスが拒否されました。
```

`install_backends.py` が自動で `opencc` をコメントアウト + `opencc-python-reimplemented` に差し替えるため、最新版なら発生しません。もし発生したら `scripts/install_backends.py` の `strip_opencc_from_requirements` が True になっているか確認。

### CUDA が認識されない(`CUDA: False`)

原因候補(多い順):
1. **CPU版 torch が上書きインストールされた**(GPT-SoVITS 依存が連れてきた)
2. NVIDIA ドライバが古い / インストールされていない
3. WSL / コンテナ内で実行していて GPU が見えていない

対処:
```batch
nvidia-smi                 REM GPU が見えるか
pip show torch             REM +cu121 などのサフィックスを確認
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --force-reinstall
```

### `ModuleNotFoundError: No module named 'ffmpeg'` 等

GPT-SoVITS の requirements.txt のインストールが途中で止まっている可能性。再実行:
```batch
pip install -r external\GPT-SoVITS\requirements.txt
```

### `ModuleNotFoundError: No module named 'sounddevice'`

```batch
pip install sounddevice
```

### DLL ロード中のアクセス拒否

```
ERROR: Could not install packages due to an OSError: [WinError 5] ...
```
別の Python プロセスが当該 DLL を掴んでいるのが原因。SAIVerse バックエンドを停止 → 再インストール:
```batch
REM SAIVerse 停止後
Get-Process python | Stop-Process -Force    REM 注意: 全 python が止まる
pip install -r external\GPT-SoVITS\requirements.txt
```

### 音が鳴らない

1. `TTS wav saved: ...` のログが出ているか確認(出ていれば合成は成功)
2. `sounddevice.query_devices()` で既定出力を確認
3. リモートデスクトップ運用なら既定は「リモート オーディオ」になるので適切
4. ローカル PC のスピーカーに鳴らしたいのに「リモート オーディオ」が既定なら `output_device` を明示
5. wav 自体を既定プレイヤーで開いて音があるか確認:
   ```batch
   start %USERPROFILE%\.saiverse\user_data\voice\out\<最新>.wav
   ```

### 合成が極端に遅い(2分以上)

- CUDA がオフ → GPU で動いていない。`nvidia-smi` で VRAM が増えているか確認
- モデルサイズ過大 → GPT-SoVITS は数十秒以内で完了するはず。その範囲を超えるなら CUDA の問題
- 参照音声が長すぎる → 3〜10秒程度がベスト

### fast-langdetect のキャッシュディレクトリエラー

```
TTS synthesis failed (engine=gpt_sovits): fast-langdetect: Cache directory not found: ...\fast_langdetect
```
`install_backends.py` の最新版では自動作成されます。旧版で発生した場合:
```batch
mkdir external\GPT-SoVITS\GPT_SoVITS\pretrained_models\fast_langdetect
```

### Tailscale 越しで音が鳴らない(リモートクライアント)

現状、バックエンド PC のスピーカー出力のみ対応しています。リモートクライアントへの音声配信は、本体側のアドオンフレームワーク(開発中)と連携して将来対応予定です。バックエンド PC の出力先を「リモート オーディオ」に設定すれば、RDP 接続中のクライアントで鳴らすことは可能です:

```json
// config/default.json
{
    "output_device": 1  // "リモート オーディオ" のデバイス番号
}
```
設定後 SAIVerse を再起動。

## 他のバックエンド

### Irodori-TTS(実験的)

```batch
setup.bat irodori
```

本環境での動作検証が完了していないため扱いは実験的です。`registry.json` の `engine` を `irodori` に変更して使用。

### 全バックエンド一括導入

```batch
setup.bat all
```

現時点でサポートしているのは GPT-SoVITS と Irodori-TTS の 2 つです。

## 自動アンインストール

```batch
rmdir /S /Q external
del /Q voice_profiles\samples\_default\ref.wav
```
パック Python 依存は SAIVerse の `.venv` に残ります(他用途との共有のため)。完全削除は:
```batch
pip uninstall -y sounddevice soundfile opencc-python-reimplemented
```
