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
| 1/5 | パック依存 (numpy, sounddevice, soundfile, huggingface_hub, **lameenc**) を SAIVerse の `.venv` にインストール |
| 2/5 | `scripts/install_backends.py` 呼び出し — GPT-SoVITS を clone、上流 requirements.txt から `opencc` を自動除外、`opencc-python-reimplemented` 代替導入、重み(約4GB)を HuggingFace から DL、`fast_langdetect` キャッシュディレクトリ作成 |
| 3/5 | `torch.cuda.is_available()` を確認し、CPU 版 torch が入っていれば `cu121` の CUDA 版を強制再導入 |
| 4/5 | `sounddevice.query_devices()` で出力デバイスを列挙(サーバー側再生時のデバイス選択用) |
| 5/5 | `voice_profiles/samples/_default/ref.wav` の有無を確認 |

所要時間: GPU環境で 5〜15分(重みDL律速)。

> `lameenc` は PCM → MP3 エンコードに使用 (progressive 配信用)。PyPI の wheel に libmp3lame がバンドルされているため、Windows でも追加システム依存は不要です。

### セットアップ完了後の手動作業

#### 1. 参照音声の配置

**方法 A: アドオン管理 UI からアップロード (推奨)**

SAIVerse 起動後、ブラウザで:
1. サイドバー → アドオン管理 → Voice TTS を展開
2. 「ペルソナ別設定」のプルダウンから対象ペルソナを選択
3. 「参照音声」にファイルをドラッグ&ドロップ or クリックしてアップロード
4. 「参照音声の書き起こし」に wav の内容を正確に入力

**方法 B: ファイル直置き**

```
voice_profiles/samples/_default/ref.wav
```
- **3秒以上10秒以内**(必須)、16kHz以上、mono、日本語の肉声
- 話速・感情が落ち着いていて背景雑音の無いクリップを推奨

#### 2. 参照テキスト(書き起こし)の調整

アドオン UI でアップロードした場合は UI の「参照音声の書き起こし」欄に入力。ファイル直置きの場合は `voice_profiles/registry.json` の `_default.ref_text` を wav の**正確な**書き起こしに差し替え。句読点まで含めて合わせると品質が向上します。

#### 3. 再生方式の選択

アドオン管理 UI の Voice TTS セクション:

| 項目 | 既定 | 変更するケース |
|---|---|---|
| クライアント側再生 | **ON** | 常に ON で OK (Tailscale 含む全環境で動作) |
| サーバー側再生 | **OFF** | バックエンド PC のスピーカーから直接鳴らしたい時 |
| 出力オーディオデバイス | `<default>` | サーバー側再生で既定以外のデバイスに出したい時 |
| ストリーミング推論 | ON | 低レイテンシ優先。OFF だと合成完了後に一括再生 |

#### 4. SAIVerse 起動

```batch
cd %USERPROFILE%\SAIVerse
.venv\Scripts\activate
python main.py city_a
```

別ターミナルで Next.js フロント:

**モバイル / Tailscale 運用する場合は production build を推奨**:
```batch
cd %USERPROFILE%\SAIVerse\frontend
npm run build
npm run start
```

**開発時 (dev mode)**:
```batch
cd %USERPROFILE%\SAIVerse\frontend
npm run dev
```

> **dev mode vs production の違いについて**: `npm run dev` はホットリロード等の開発用機能でオーバーヘッドが大きく、iOS Safari が SAIVerse タブを自動破棄する事象が観測されています。モバイルから利用する運用では必ず `npm run build && npm run start` を使ってください。

ブラウザで `http://localhost:3000` → 適当なペルソナに話しかけると音声が鳴ります。Tailscale 越しの場合は割り当てられた `*.ts.net` ホスト名で。

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

`requirements.txt` の主な内容:
- `numpy>=1.24`
- `sounddevice>=0.4.6` — サーバー側スピーカー再生
- `soundfile>=0.12` — wav 入出力
- `huggingface_hub>=0.20` — 重みダウンロード
- `lameenc>=1.5` — PCM → MP3 progressive エンコーダ (クライアント配信)

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

代表的なハマりどころのみ記載。詳細は [TROUBLESHOOTING.md](TROUBLESHOOTING.md) を参照してください。

### opencc のビルドエラー

`install_backends.py` が自動で `opencc` をコメントアウト + `opencc-python-reimplemented` に差し替えるため、最新版なら発生しません。詳細は TROUBLESHOOTING.md。

### CUDA が認識されない(`CUDA: False`)

最多原因は「GPT-SoVITS 依存が CPU 版 torch を上書きインストールした」:
```batch
nvidia-smi                 REM GPU が見えるか
pip show torch             REM +cu121 などのサフィックスを確認
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --force-reinstall
```

### `ModuleNotFoundError: No module named 'lameenc'`

```batch
pip install lameenc
```

### DLL ロード中のアクセス拒否

別の Python プロセスが当該 DLL を掴んでいるのが原因:
```batch
Get-Process python | Stop-Process -Force
pip install -r external\GPT-SoVITS\requirements.txt
```

### モバイルで音が鳴らない / タブがリロードされる

Next.js を **production build** で起動しているか確認:
```batch
cd %USERPROFILE%\SAIVerse\frontend
npm run build
npm run start
```
dev mode はモバイル Safari でタブ自動破棄される事象あり。詳細は TROUBLESHOOTING.md。

### 初回の音声が鳴らない

モバイルブラウザの autoplay ポリシーで、最初のユーザー操作前は音声再生が拒否される。**SAIVerse の画面を 1 回タップ**してからペルソナに話しかけると鳴ります。詳細は TROUBLESHOOTING.md。

## 他のバックエンド

### Irodori-TTS

```batch
setup.bat irodori
```

動作検証・速度最適化・疑似ストリーミング対応済。CUDA 必須、bf16 推奨。使用方法:

- **アドオン管理 UI**: ペルソナ別設定 →「TTS エンジン」を `irodori` に切替
- **registry.json**: 該当ペルソナエントリの `engine` を `irodori` に変更

Irodori は参照音声のみから話者特徴を推定するため `ref_text` は無視されます。内部パラメータは `num_steps`(既定 24)、`truncation_factor`(既定 0.75、ゴミ抑制に重要)。RTF 0.3x 程度で再生に追い付くのでモバイル/Tailscale 運用も問題なし。

### 全バックエンド一括導入

```batch
setup.bat all
```

現時点でサポートしているのは GPT-SoVITS と Irodori-TTS の 2 つです。

## アンインストール

```batch
rmdir /S /Q external
del /Q voice_profiles\samples\_default\ref.wav
```
パック Python 依存は SAIVerse の `.venv` に残ります(他用途との共有のため)。完全削除は:
```batch
pip uninstall -y sounddevice soundfile opencc-python-reimplemented lameenc
```
