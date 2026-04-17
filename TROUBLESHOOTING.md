# トラブルシューティングガイド

saiverse-voice-tts 拡張パックで発生しやすい問題と、その診断手順・解決方法をまとめています。

---

## 目次

### セットアップ関連
- [setup.bat が途中で止まる](#setupbat-が途中で止まる)
- [opencc のビルドエラー(Windows)](#opencc-のビルドエラーwindows)
- [editdistance のビルドエラー(Python 3.13+)](#editdistance-のビルドエラーpython-313)
- [ModuleNotFoundError が出る](#modulenotfounderror-が出る)
- [DLL アクセス拒否エラー(pip install 時)](#dll-アクセス拒否エラーpip-install-時)

### GPU / CUDA 関連
- [CUDA が認識されない(`CUDA: False`)](#cuda-が認識されないcuda-false)
- [GPU が複数あるがどちらが使われるかわからない](#gpu-が複数あるがどちらが使われるかわからない)
- [GPU 稼働率が 0% のまま](#gpu-稼働率が-0-のまま)
- [CUDA out of memory (VRAM 不足)](#cuda-out-of-memory-vram-不足)

### TTS 合成関連
- [🔊ボタンがずっと「準備中」のまま](#ボタンがずっと準備中のまま)
- [合成が極端に遅い(2分以上)](#合成が極端に遅い2分以上)
- [合成は成功するが音が鳴らない](#合成は成功するが音が鳴らない)
- [fast-langdetect のキャッシュディレクトリエラー](#fast-langdetect-のキャッシュディレクトリエラー)
- [文字化けしたテキストが読み上げられる](#文字化けしたテキストが読み上げられる)
- [参照音声と異なる声で合成される](#参照音声と異なる声で合成される)

### 音声再生関連
- [サーバー PC のスピーカーから音が出ない](#サーバー-pc-のスピーカーから音が出ない)
- [ブラウザの🔊ボタンで音が出ない](#ブラウザのボタンで音が出ない)
- [Tailscale / リモートデスクトップ越しで音が出ない](#tailscale--リモートデスクトップ越しで音が出ない)
- [音声が途切れる / スタッターする](#音声が途切れる--スタッターする)

### アドオン管理 UI 関連
- [アドオン管理画面でトグルが反映されない](#アドオン管理画面でトグルが反映されない)
- [ペルソナ別設定でペルソナが追加できない](#ペルソナ別設定でペルソナが追加できない)
- [参照音声のアップロードが失敗する](#参照音声のアップロードが失敗する)

### SSE / ネットワーク関連
- [`[addon-events proxy] upstream fetch failed` が連続する](#addon-events-proxy-upstream-fetch-failed-が連続する)
- [ページリロードで再生ボタンが準備中に戻る](#ページリロードで再生ボタンが準備中に戻る)

---

## セットアップ関連

### setup.bat が途中で止まる

**診断**: エラーメッセージを確認。以下のどれに該当するか:

| エラーメッセージ | 原因 | 対処 |
|---|---|---|
| `SAIVerse virtual environment not found` | 本体の `.venv` 未作成 | SAIVerse 本体の `setup.bat` を先に実行 |
| `Failed building wheel for opencc` | Windows C++ ビルド失敗 | [opencc セクション](#opencc-のビルドエラーwindows)参照 |
| `Failed building wheel for editdistance` | Python 3.13+ 問題 | [editdistance セクション](#editdistance-のビルドエラーpython-313)参照 |
| `OSError: [WinError 5]` | DLL ロック | [DLL アクセス拒否](#dll-アクセス拒否エラーpip-install-時)参照 |
| `error: subprocess-exited-with-error` | pip install 中の個別パッケージ失敗 | エラー直前のパッケージ名を確認して個別対処 |

**一般的な再試行手順**:
```powershell
# SAIVerse の全 Python プロセスを停止
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# 再実行
cd <SAIVerse>\expansion_data\saiverse-voice-tts
setup.bat
```

### opencc のビルドエラー(Windows)

```
error: [WinError 5] アクセスが拒否されました。
Failed to build opencc
```

**原因**: `opencc` パッケージの C++ ソースビルドが Windows で失敗する。

**解決**: `install_backends.py` の最新版では自動的に以下を行います:
1. `opencc-python-reimplemented`(純 Python 互換パッケージ)を先行インストール
2. GPT-SoVITS の requirements.txt から `opencc` 行を自動コメントアウト

古いバージョンで発生する場合は手動で:
```powershell
pip install opencc-python-reimplemented
# external/GPT-SoVITS/requirements.txt を開き、opencc 行と --no-binary=opencc 行をコメントアウト
pip install -r external\GPT-SoVITS\requirements.txt
```

### editdistance のビルドエラー(Python 3.13+)

```
error: command 'cl.exe' failed: ...
warning C4819: ファイルは、現在のコード ページ (932) で表示できない文字を含んでいます
```

**原因**: Python 3.13 以降では `editdistance` の Windows 向けビルド済み wheel が未提供で、MSVC ソースビルドが走る。日本語 Windows の CP932 ロケールだと非 ASCII 文字でコンパイルエラーになる。

**解決**: `install_backends.py` と `setup.bat` の最新版では `CL=/utf-8` 環境変数を自動設定済み。

古いバージョンの場合は手動で:
```powershell
$env:CL = "/utf-8"
pip install editdistance
```

### ModuleNotFoundError が出る

| モジュール名 | 原因 | 対処 |
|---|---|---|
| `sounddevice` | パック依存未インストール | `pip install sounddevice` |
| `ffmpeg` | GPT-SoVITS 依存未完了 | `pip install ffmpeg-python` |
| `pytorch_lightning` | 同上 | `pip install -r external\GPT-SoVITS\requirements.txt` |
| `TTS_infer_pack` | GPT-SoVITS clone 未完了 | `python scripts\install_backends.py gpt_sovits` |
| `qwen_tts` | Qwen3-TTS 未インストール | サポート外(GPT-SoVITS を使用してください) |

**包括的な修復**:
```powershell
cd <SAIVerse>\expansion_data\saiverse-voice-tts
pip install -r requirements.txt
python scripts\install_backends.py gpt_sovits
```

### DLL アクセス拒否エラー(pip install 時)

```
ERROR: Could not install packages due to an OSError: [WinError 5] ...onnxruntime_providers_shared.dll
```

**原因**: 別の Python プロセスが DLL をロード中でロックしている。

**解決**:
```powershell
# 1. SAIVerse バックエンドを停止(Ctrl+C)
# 2. 残存プロセスも停止
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# 3. pip 一時ファイルのゴミを掃除
Remove-Item -Recurse -Force "$env:USERPROFILE\SAIVerse\.venv\Lib\site-packages\~*" -ErrorAction SilentlyContinue

# 4. 再インストール
pip install -r external\GPT-SoVITS\requirements.txt
```

---

## GPU / CUDA 関連

### CUDA が認識されない(`CUDA: False`)

**診断**:
```powershell
# Step 1: GPU ドライバが入っているか
nvidia-smi
# → 表示されない場合: NVIDIA ドライバをインストール

# Step 2: torch のバージョン確認
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
# → "+cpu" が含まれていたら CPU 版 torch
```

**原因と対処**(多い順):

| 原因 | 確認方法 | 対処 |
|---|---|---|
| CPU 版 torch がインストールされた | `pip show torch` で `+cpu` | CUDA 版を再導入(下記) |
| NVIDIA ドライバ未インストール | `nvidia-smi` が通らない | [NVIDIA ドライバ](https://www.nvidia.com/drivers)をインストール |
| GPT-SoVITS 依存が torch を上書きした | setup.bat 実行直後に `+cpu` に変わった | CUDA 版を再導入(下記) |
| WSL/Docker 内で GPU 非公開 | `nvidia-smi` が通らない | WSL の GPU パススルー設定を確認 |

**CUDA 版 torch の再導入**(最も多い原因の修復):
```powershell
pip uninstall -y torch torchaudio torchvision
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

CUDA 12.x 環境の場合は `cu121` を、CUDA 11.x なら `cu118` を使用。`nvidia-smi` の右上に表示される CUDA Version を確認:
```
+-------------------------------------------+
| NVIDIA-SMI 5xx.xx    CUDA Version: 12.x   |
+-------------------------------------------+
```

### GPU が複数あるがどちらが使われるかわからない

**診断**:
```powershell
# 全 GPU の状態を表示
nvidia-smi

# Python から見える GPU 一覧
python -c "import torch; [print(f'GPU {i}: {torch.cuda.get_device_name(i)}, VRAM {torch.cuda.get_device_properties(i).total_mem / 1024**3:.1f} GB') for i in range(torch.cuda.device_count())]"
```

**GPT-SoVITS が使う GPU を指定する方法**:

方法1: 環境変数で制限(推奨):
```powershell
# GPU 0 のみ使用
$env:CUDA_VISIBLE_DEVICES = "0"
python main.py city_a

# GPU 1 のみ使用
$env:CUDA_VISIBLE_DEVICES = "1"
python main.py city_a
```

方法2: `config/default.json` のエンジン設定で指定:
```json
{
    "engines": {
        "gpt_sovits": {
            "ref_language": "ja",
            "target_language": "ja"
        }
    }
}
```
GPT-SoVITS は内部で `tts_infer.yaml` の `device: cuda` を使用。特定 GPU を指定するには `CUDA_VISIBLE_DEVICES` が最も確実。

**合成中にどの GPU が使われているか確認**:
```powershell
# 別ターミナルで実行。合成中に VRAM 使用量が増える GPU が対象
nvidia-smi -l 1
```

### GPU 稼働率が 0% のまま

**診断**: 合成中に `nvidia-smi` で確認:
```powershell
nvidia-smi
```

| 状態 | 意味 |
|---|---|
| Memory-Usage が数 GB + GPU-Util 30-100% | 正常に GPU 推論中 |
| Memory-Usage が 899MB 等(最小) + GPU-Util 0% | **GPU に載っていない = CPU 推論** |
| Memory-Usage が数 GB + GPU-Util 0% | モデルはロードされたが推論開始前 or ハング |

**原因と対処**:

1. **CUDA 版 torch でない** → [CUDA が認識されない](#cuda-が認識されないcuda-false)を参照
2. **GPT-SoVITS の `tts_infer.yaml` の device が `cpu` になっている**:
   ```powershell
   # 確認
   Select-String -Path "external\GPT-SoVITS\GPT_SoVITS\configs\tts_infer.yaml" -Pattern "device:"
   ```
   `custom:` セクションの `device: cuda` であることを確認。`cpu` になっていたら `cuda` に変更。
3. **CUDA_VISIBLE_DEVICES が空文字に設定されている**: `echo $env:CUDA_VISIBLE_DEVICES` で確認

### CUDA out of memory (VRAM 不足)

```
RuntimeError: CUDA out of memory. Tried to allocate XXX MiB
```

**GPT-SoVITS の VRAM 消費目安**: 約 2〜4 GB(モデルロード時)

**対処**:
```powershell
# 1. 他の GPU プロセスを確認
nvidia-smi

# 2. 不要なプロセスを停止(Chrome の GPU プロセス等は多くの VRAM を消費する)

# 3. GPT-SoVITS の is_half を有効化(VRAM 半減、品質微減):
# external/GPT-SoVITS/GPT_SoVITS/configs/tts_infer.yaml の custom セクションで
# is_half: true
```

VRAM が 4GB 未満の GPU では GPT-SoVITS は厳しいため、6GB 以上推奨。

---

## TTS 合成関連

### 🔊ボタンがずっと「準備中」のまま

**診断フロー**:

```
ステップ1: TTS 合成自体が完了しているか
  → ログで "TTS wav saved" or "TTS streamed wav saved" が出ているか確認
  
ステップ2: message_id が取得できているか
  → ログで "enqueue: job=... message_id=..." を確認
  → message_id=None なら本体側の set_active_message_id 配線問題

ステップ3: addon_metadata に登録されたか
  → ログで "notify_audio_ready: msg=... metadata=True event=True" を確認

ステップ4: SSE イベントが配信されたか
  → ログで "addon_events: emit ... subscribers=N" を確認
  → subscribers=0 なら SSE 接続問題

ステップ5: フロントが受信しているか
  → ブラウザ DevTools Console で [addon-events] ログを確認
```

**ログの確認方法**:
```powershell
$log = (Get-ChildItem $env:USERPROFILE\.saiverse\user_data\logs -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName + "\backend.log"
Select-String -Path $log -Pattern "enqueue: job=|notify_audio_ready|addon_events.*emit|TTS wav saved|TTS streamed" -Encoding UTF8 | Select-Object -Last 20
```

**各ステップの解決策**:

| ステップ | 原因 | 解決 |
|---|---|---|
| 1 で止まる | TTS エンジンのロードまたは合成が失敗 | [合成が遅い](#合成が極端に遅い2分以上)または[GPU 関連](#gpu--cuda-関連)を参照 |
| 2 で message_id=None | 本体側の ContextVar 配線不備 | SAIVerse 本体を最新版に更新 |
| 3 で metadata=False | `saiverse.addon_metadata` モジュール未提供 | 本体のアドオン基盤が必要 |
| 4 で subscribers=0 | SSE 未接続 | [SSE セクション](#addon-events-proxy-upstream-fetch-failed-が連続する)参照 |
| 5 で未受信 | フロント側の購読問題 | ブラウザ Ctrl+Shift+R でハードリロード |

### 合成が極端に遅い(2分以上)

**診断**:
```powershell
# 合成中に GPU 使用状況を確認
nvidia-smi

# ログで合成時間を確認
Select-String -Path $log -Pattern "TTS wav saved|TTS streamed wav saved|first chunk ready" -Encoding UTF8 | Select-Object -Last 5
```

**原因と対処**:

| 症状 | 原因 | 対処 |
|---|---|---|
| GPU-Util 0%, VRAM 最小 | CPU で推論している | [CUDA 認識](#cuda-が認識されないcuda-false)を確認 |
| GPU-Util 30%+, 初回のみ遅い | モデルロード(正常) | 2回目以降は数秒。初回は10-30秒が正常 |
| 毎回2分以上 | ストリーミング OFF で長文合成 | アドオン設定で「ストリーミング推論」を ON に |
| 参照音声が30秒以上 | 参照音声が長すぎる | 3〜10秒に切り詰める |

### 合成は成功するが音が鳴らない

**診断**: ログに `TTS wav saved` が出ているのに音が出ない場合:

```powershell
# 1. sounddevice の出力デバイス一覧
python -c "import sounddevice as sd; print(sd.query_devices())"
# "<" マークが既定出力デバイス

# 2. 生成された wav を直接再生して音があるか確認
$latest = Get-ChildItem "$env:USERPROFILE\.saiverse\user_data\voice\out\*.wav" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
start $latest.FullName

# 3. sounddevice の手動テスト
python -c "import soundfile as sf, sounddevice as sd; d,sr = sf.read('$($latest.FullName)'); sd.play(d, sr, device=<デバイス番号>, blocking=True); print('done')"
```

**対処**:

| 状態 | 対処 |
|---|---|
| wav を直接開くと音はある | `config/default.json` の `output_device` を正しいデバイス番号に設定 |
| wav が無音(サイズが数 KB) | 参照音声か `ref_text` が不適切。[参照音声と異なる声](#参照音声と異なる声で合成される)参照 |
| sounddevice not installed | `pip install sounddevice` |
| `PortAudio` エラー | sounddevice の再インストール: `pip install --force-reinstall sounddevice` |

### fast-langdetect のキャッシュディレクトリエラー

```
TTS synthesis failed (engine=gpt_sovits): fast-langdetect: Cache directory not found
```

**解決**:
```powershell
mkdir external\GPT-SoVITS\GPT_SoVITS\pretrained_models\fast_langdetect
```
`install_backends.py` の最新版では自動作成されます。

### 文字化けしたテキストが読み上げられる

**原因**: Markdown のリンク URL (saiverse://... の UUID 等) が除去されずに TTS に渡されている。

**確認**:
```powershell
Select-String -Path $log -Pattern "speak_as_persona enqueued" -Encoding UTF8 | Select-Object -Last 3
```
ログの `len=` と `orig_len=` を比較。差がなければテキストクリーナーが動作していない。

**解決**: 拡張パックを最新版に更新。`tools/speak/text_cleaner.py` が存在するか確認。

### 参照音声と異なる声で合成される

**確認ポイント**:

1. **参照音声の長さ**: 3秒未満は声紋抽出が不安定。3〜10秒推奨
   ```powershell
   python -c "import soundfile as sf; d,sr = sf.read(r'voice_profiles\samples\_default\ref.wav'); print(f'{len(d)/sr:.1f}秒 {sr}Hz')"
   ```

2. **ref_text と実際の発話内容の一致**: `registry.json` の `ref_text` が参照音声の書き起こしと正確に一致しているか(句読点含む)

3. **参照音声の品質**:
   - 背景雑音・BGM がない
   - リップノイズが少ない
   - 感情の起伏が極端でない(フラット推奨)
   - モノラル推奨(ステレオは片チャンネルのみ使用される場合あり)

4. **エンジン設定**: `registry.json` 内の `params.temperature` が高すぎると声質がブレる。`0.7〜1.0` 推奨

---

## 音声再生関連

### サーバー PC のスピーカーから音が出ない

**診断**:
```powershell
# 1. 合成ログ確認
Select-String -Path $log -Pattern "TTS wav saved|TTS streamed" -Encoding UTF8 | Select-Object -Last 3

# 2. sounddevice デバイス一覧
python -c "import sounddevice as sd; print(sd.query_devices())"

# 3. アドオン設定でサーバー側再生が ON か
python -c "from saiverse.addon_config import get_params; p = get_params('saiverse-voice-tts'); print('server_side_playback:', p.get('server_side_playback'))"
```

**対処**:

| 状態 | 対処 |
|---|---|
| `server_side_playback: False` | アドオン管理 UI で「サーバー側再生」を ON に |
| デバイスが「リモート オーディオ」 | `config/default.json` の `output_device` を実デバイス番号に |
| sounddevice not installed | `pip install sounddevice` |
| 合成ログ自体がない | [準備中のまま](#ボタンがずっと準備中のまま)を参照 |

### ブラウザの🔊ボタンで音が出ない

**診断**(ブラウザ DevTools):

1. **Network タブ**: 🔊ボタンクリック後に `/api/addon/saiverse-voice-tts/audio/...` リクエストが出るか
2. **Console タブ**: `[PlayAudioButton]` 関連のエラーが出ているか

**対処**:

| 症状 | 原因 | 対処 |
|---|---|---|
| Network に audio リクエストが出ない | ボタンのクリックハンドラが未発火 | Ctrl+Shift+R でハードリロード |
| 404 返却 | `audio_file` メタデータ未登録 or wav ファイル削除済み | 新規発話でテスト |
| 200 だが無音 | `Content-Disposition: attachment` キャッシュ | Ctrl+Shift+R でハードリロード |
| `DOMException: NotAllowedError` | ブラウザ autoplay 制約 | ユーザー操作(クリック)後に再生を試行 |

**直接再生テスト**(ブラウザアドレスバーに):
```
http://localhost:3000/api/addon/saiverse-voice-tts/audio/<message_id>
```
音声プレイヤーが出て再生できれば配信は正常。ボタン UI の問題。

### Tailscale / リモートデスクトップ越しで音が出ない

**現状の動作**:
- **サーバー側再生**: バックエンド PC のスピーカーから鳴る(RDP 越しなら「リモート オーディオ」デバイス経由でクライアント PC で聞こえる)
- **ブラウザ再生**: 🔊ボタンクリックでクライアント側ブラウザから鳴る

**サーバー側再生をリモートで聞く**:
```powershell
# 1. リモート オーディオのデバイス番号を確認
python -c "import sounddevice as sd; print(sd.query_devices())"
# "<" マーク or 名前に「リモート」を含むデバイス番号を控える

# 2. config/default.json に設定
# { "output_device": <デバイス番号> }

# 3. SAIVerse 再起動
```

**RDP のオーディオリダイレクト設定**:
1. mstsc.exe → 「オプションの表示」 → 「ローカル リソース」
2. 「リモート オーディオ」の「設定」
3. 「このコンピューターで再生」を選択

**注意**: MediaRecorder(マイク入力)は HTTPS が必要。Tailscale 経由の HTTP では動作しない場合あり。

### 音声が途切れる / スタッターする

**原因**: ストリーミング再生時に合成速度が再生速度に追いつかない。

**対処**:
1. **ストリーミングを OFF にする**: アドオン管理 UI で「ストリーミング推論」を OFF → 合成完了後に一括再生(途切れなし、ただし話し始めが遅くなる)
2. **GPU 負荷を下げる**: 他の GPU プロセスを停止
3. **テキスト分割を細かくする**: `voice_profiles/registry.json` で `"text_split_method": "cut1"` に変更(文単位で分割、チャンクが早く出る)

---

## アドオン管理 UI 関連

### アドオン管理画面でトグルが反映されない

**診断**:
```powershell
# 本体側の addon_config API が提供されているか
python -c "from saiverse.addon_config import get_params; print(get_params('saiverse-voice-tts'))"
```

**対処**:
- `get_params` が `ImportError` → SAIVerse 本体がアドオン基盤未対応。本体を最新版に更新
- `get_params` は通るが値が変わらない → ブラウザで設定変更後に SAIVerse を再起動(設定はランタイムでキャッシュされないが、Toolが新しい pulse で読み直す)

### ペルソナ別設定でペルソナが追加できない

**症状**: 「ペルソナ別設定」のラベルだけ表示され、「+」ボタンがない。

**原因**: `GET /api/people/` エンドポイントが 404 を返している。

**確認**:
```powershell
# ブラウザで直接アクセス
# http://localhost:3000/api/people/
# → JSON 配列が返れば OK、404 ならエンドポイント未実装
```

**対処**: SAIVerse 本体を最新版(`feature/tts-addon-integration-fixes` 以降)に更新。

### 参照音声のアップロードが失敗する

**診断**: アドオン管理 UI で参照音声をアップロードした際のエラーメッセージを確認。

| エラー | 原因 | 対処 |
|---|---|---|
| `File type 'xxx' not allowed` | 対応外のファイル形式 | wav / mp3 / flac / ogg のみ対応 |
| `File too large` | サイズ上限超過 | 50MB 以下のファイルを使用 |
| `Invalid name` | persona_id に特殊文字 | persona_id は英数字・ハイフン・アンダースコアのみ |
| `Addon manifest not found` | addon.json が読めない | 拡張パックの配置を確認 |
| `Upload failed` (汎用) | バックエンドとの通信失敗 | バックエンドが起動しているか確認 |

---

## SSE / ネットワーク関連

### `[addon-events proxy] upstream fetch failed` が連続する

**原因**: Next.js の SSE プロキシがバックエンドに接続できない。

**状況別**:

| タイミング | 問題か | 対処 |
|---|---|---|
| バックエンド起動前/起動中 | **正常** | バックエンド起動完了後に自動再接続 |
| バックエンド起動後も継続 | **問題** | 以下を確認 |

**バックエンド起動後も出る場合**:
```powershell
# 1. バックエンドが 8000 番で listen しているか
Test-NetConnection -ComputerName 127.0.0.1 -Port 8000

# 2. /api/addon/events が応答するか
python -c "import requests; r = requests.get('http://127.0.0.1:8000/api/addon/events', stream=True, timeout=3); print(r.status_code, r.headers.get('content-type'))"
# 期待: 200 text/event-stream

# 3. ルーティング順序の問題 (404 "Addon not found")
# → api/main.py で addon_events.router が addon.router より先に登録されているか確認
```

### ページリロードで再生ボタンが準備中に戻る

**原因と対処**:

| 原因 | 確認 | 対処 |
|---|---|---|
| metadata 先読みが動いていない | DevTools Network で `/api/addon/messages/.../metadata` リクエストを確認 | SAIVerse 本体を最新版に更新(page.tsx に prefetch 処理が必要) |
| メタデータが DB に無い | 上記リクエストが 200 で空 | 新規発話で再テスト |
| wav ファイルが GC で削除済み | `~/.saiverse/user_data/voice/out/` にファイルがあるか | `config/default.json` の `gc_hours` を延長(既定 24 時間) |

---

## 共通の診断コマンド集

### バックエンドログの監視(リアルタイム)
```powershell
$log = (Get-ChildItem $env:USERPROFILE\.saiverse\user_data\logs -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName + "\backend.log"
Get-Content -Path $log -Wait -Tail 0 -Encoding UTF8 | Select-String -Pattern "speak_as_persona|TTS wav|TTS synthesis|first chunk|notify_audio_ready|addon_events.*emit"
```

### GPU 状態の継続監視
```powershell
nvidia-smi -l 2
```

### アドオン設定の現在値
```powershell
python -c "from saiverse.addon_config import get_params; import json; print(json.dumps(get_params('saiverse-voice-tts'), indent=2, ensure_ascii=False))"
```

### ペルソナ別設定の確認
```powershell
python -c "from saiverse.addon_config import get_params; import json; print(json.dumps(get_params('saiverse-voice-tts', persona_id='Yui_city_a'), indent=2, ensure_ascii=False))"
```

### Tool 登録状況
```powershell
python -c "from tools import TOOL_REGISTRY; print('speak_as_persona:', 'speak_as_persona' in TOOL_REGISTRY, '/ total:', len(TOOL_REGISTRY))"
```

### 生成済み wav ファイル一覧(最新5件)
```powershell
Get-ChildItem "$env:USERPROFILE\.saiverse\user_data\voice\out\*.wav" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | Format-Table Name, Length, LastWriteTime
```

### 保存済みメタデータの確認
```powershell
python -c "
from database.models import AddonMessageMetadata
from database.session import SessionLocal
db = SessionLocal()
rows = db.query(AddonMessageMetadata).filter(AddonMessageMetadata.addon_name == 'saiverse-voice-tts').order_by(AddonMessageMetadata.created_at.desc()).limit(5).all()
for r in rows:
    print(f'msg={r.message_id} key={r.key} value={(r.value or \"\")[:60]}')
db.close()
"
```
