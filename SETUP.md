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
| 1/5 | パック依存 (numpy, sounddevice, soundfile, huggingface_hub, **lameenc**, **torchcodec**) を SAIVerse の `.venv` にインストール |
| 2/5 | `scripts/install_backends.py` 呼び出し — GPT-SoVITS を clone、上流 requirements.txt から `opencc` を自動除外、`opencc-python-reimplemented` 代替導入、重み(約4GB)を HuggingFace から DL、`fast_langdetect` キャッシュディレクトリ作成 |
| 3/5 | `torch.cuda.is_available()` を確認し、CPU 版 torch が入っていれば `cu121` の CUDA 版を強制再導入 |
| 4/5 | `sounddevice.query_devices()` で出力デバイスを列挙(サーバー側再生時のデバイス選択用) |
| 5/5 | `voice_profiles/samples/_default/ref.wav` の有無を確認 |

所要時間: GPU環境で 5〜15分(重み DL 律速)。

> `lameenc` は PCM → MP3 エンコードに使用 (progressive 配信用)。PyPI の wheel に libmp3lame がバンドルされているため、Windows でも追加システム依存は不要です。
>
> `torchcodec` は Irodori-TTS の内部で呼ぶ `torchaudio.load` が torch 2.10+ 系で必要とします。GPT-SoVITS のみの運用でも事前にインストールしています(エンジン切替時に追加セットアップ不要にするため)。

### セットアップ完了後の手動作業

#### 1. 参照音声の配置

**方法 A: アドオン管理 UI からアップロード (推奨)**

SAIVerse 起動後、ブラウザで:
1. サイドバー → アドオン管理 → Voice TTS を展開
2. 「ペルソナ別設定」のプルダウンから対象ペルソナを選択
3. 「参照音声」にファイルをドラッグ&ドロップ or クリックしてアップロード
4. 「参照音声の書き起こし」に wav の内容を正確に入力(**irodori エンジンを使う場合は空でよい**)

**方法 B: ファイル直置き**

```
voice_profiles/samples/_default/ref.wav
```
- **3秒以上10秒以内**(必須)、16kHz以上、mono、日本語の肉声
- 話速・感情が落ち着いていて背景雑音の無いクリップを推奨

#### 2. 参照テキスト(書き起こし)の調整

アドオン UI でアップロードした場合は UI の「参照音声の書き起こし」欄に入力。ファイル直置きの場合は `voice_profiles/registry.json` の `_default.ref_text` を wav の**正確な**書き起こしに差し替え。句読点まで含めて合わせると品質が向上します。

> Irodori-TTS は参照音声のみから話者特徴を推定するため `ref_text` を使いません。GPT-SoVITS 用に書いた ref_text が混在していても無害です。

#### 3. 再生方式の選択

アドオン管理 UI の Voice TTS セクションで各トグル / ドロップダウンを設定します。既定値は **ブラウザ側再生 ON / サーバー側再生 OFF / ストリーミング推論 ON** で、Tailscale 含む多くの環境はこのままで動作します。設定項目の全リストと意味は [README の「使い方 → アドオン管理 UI」](README.md#アドオン管理-ui-推奨) を参照。

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

## Irodori-TTS を使う場合

GPT-SoVITS に加えて Irodori-TTS を**追加で**導入する手順。既に GPT-SoVITS を `setup.bat` で入れてあれば、そのまま追加インストール可能です。

### 1. Irodori バックエンドの導入

```batch
cd %USERPROFILE%\SAIVerse\expansion_data\saiverse-voice-tts
setup.bat irodori
```

内部では:

- `external/Irodori-TTS/` に upstream repo (`Aratako/Irodori-TTS`) を shallow clone
- 上流 `requirements.txt` から推論に必須なパッケージを pip install(`dacvae` / `peft` / `safetensors` / `sentencepiece` / `transformers` / `llvmlite` / `numba` 等)
- 重みを HuggingFace からダウンロード(初回のみ、計 約 2.3GB):
  - `Aratako/Irodori-TTS-500M-v2` (生成モデル、約 1.9GB)
  - `Aratako/Semantic-DACVAE-Japanese-32dim` (音声 codec、約 410MB)

所要時間: ネット回線次第で 3〜10 分。

### 2. ペルソナへの割り当て

アドオン管理 UI から:

1. サイドバー → **アドオン管理** → **Voice TTS** を展開
2. 「ペルソナ別設定」のプルダウンで対象ペルソナを選択
3. 「**TTS エンジン**」ドロップダウンを `irodori` に変更
4. 「**参照音声**」に wav をアップロード(GPT-SoVITS 用の wav を流用可、**3〜10 秒の日本語肉声**が必須)
5. 「**参照音声の書き起こし**」は**空のままで OK**(irodori では使用しない)

CLI 派の場合は `voice_profiles/registry.json` を直接編集:

```json
{
    "YourPersona_city_a": {
        "engine": "irodori",
        "ref_audio": "samples/YourPersona_city_a/ref.wav",
        "ref_text": "",
        "params": {
            "num_steps": 32,
            "seed": 42
        }
    }
}
```

### 3. 動作確認

SAIVerse バックエンドを再起動 → 対象ペルソナに話しかける。初回発話時に `Loading Irodori-TTS runtime:` のログが出て約 12 秒の初期化、その後は話し始めまで約 1.4 秒。

ログの監視コマンド:
```powershell
$log = (Get-ChildItem $env:USERPROFILE\.saiverse\user_data\logs -Directory | Sort LastWriteTime -Desc | Select -First 1).FullName + "\backend.log"
Get-Content $log -Wait -Tail 0 | Select-String "Irodori|speak_as_persona|first chunk"
```

期待されるログ抜粋:
```
[INFO] tools.speak.engine.irodori: Irodori-TTS checkpoint resolved: hf://Aratako/Irodori-TTS-500M-v2 -> ...
[INFO] tools.speak.engine.irodori: Loading Irodori-TTS runtime: Aratako/Irodori-TTS-500M-v2 (device=cuda precision=bf16)
[INFO] tools.speak.schema: speak_as_persona enqueued: persona=... job=...
```

### 4. 主な内部パラメータ

通常は触らなくて OK。チューニングしたい場合のエンジン別パラメータ一覧は [voice_profiles/README.md](voice_profiles/README.md#params-に指定できる項目エンジン別) を参照してください。`truncation_factor=0.75` は `irodori.py` 内のハードコード(ゴミ音声抑制の要で変更非推奨、設計理由は [ARCHITECTURE.md](ARCHITECTURE.md) 参照)。

## クラウド TTS エンジン (OpenAI / ElevenLabs / Azure) を使う場合

GPU を持たないユーザー向けの選択肢。**追加のソフトウェアインストール不要**で、API key を入れるだけで使えます。

### OpenAI TTS のセットアップ

#### 1. API key 取得

1. https://platform.openai.com/api-keys にアクセスしてサインイン
2. **Create new secret key** → name 入力 (例: `saiverse-tts`) → **Create**
3. 表示された `sk-...` 形式の key を **その場でコピー** (再表示は不可)
4. 課金設定: https://platform.openai.com/settings/organization/billing で **クレジットカード登録**(API は使った分だけの後払い、$5 程度を最低 deposit する形式)

#### 2. SAIVerse に登録

1. アドオン管理 → Voice TTS を展開 → デフォルト (全ペルソナ共通) の中の「**OpenAI API Key**」を展開して貼り付け
   - もしくは環境変数 `OPENAI_API_KEY` を `.env` に書いてもOK (本体既存の OpenAI 設定をそのまま流用可)
2. ペルソナ別設定でペルソナを選択 → 「**TTS エンジン**」を `openai_tts` に変更
3. 「**OpenAI 音声**」から voice を選択
   - alloy / echo / fable / onyx / nova / shimmer / ash / sage / coral の 9 種から好みのものを
   - 試聴: https://platform.openai.com/docs/guides/text-to-speech/voice-options で各 voice をプレビュー可能

#### 3. 料金目安 (2026 年 5 月時点)

| モデル | 1M 文字あたり |
|---|---|
| `tts-1` (パック既定) | **$15** |
| `tts-1-hd` (高品質) | $30 |
| `gpt-4o-mini-tts` (新世代) | $12 |

100 文字の発話 1 回 ≈ $0.0015 = 約 0.2 円。1,000 発話/月でも $1.5 程度。

最新は [OpenAI Pricing](https://openai.com/api/pricing/) を参照。

### ElevenLabs のセットアップ

#### 1. アカウント作成 + API key 取得

1. https://elevenlabs.io にアクセス → 右上「**Sign Up**」 → メール認証
2. 右上のプロフィールアイコン → **My Account** → 左サイドバー **API Keys**
   (直接アクセスなら https://elevenlabs.io/app/settings/api-keys )
3. **Create API Key** → name 入力 → Permissions は **All access** で OK
4. 表示された `sk_...` 形式の key を **その場でコピー** (再表示は不可、なくしたら作り直し)

#### 2. ボイスクローン作成 (Voice ID 取得)

1. 左サイドバー **Voice Lab** → **Add Voice** → **Instant Voice Cloning**
2. ペルソナの参照音声 wav を upload (推奨: 1〜5 分のクリーンな日本語肉声、3〜5 分がベスト)
3. ボイス名と説明を入力 → **Add Voice** で作成
4. 作成されたボイスをクリック → **Voice ID** をコピー (例: `21m00Tcm4TlvDq8ikWAM`)

> **Note**: Free プランでも IVC 3 枠まで使えるので、課金前に 1 ペルソナで試して声の質を確認できます。

#### 3. SAIVerse に登録

1. アドオン管理 → Voice TTS → デフォルトの「**ElevenLabs API Key**」(アコーディオン) に貼り付け
   - 環境変数 `ELEVENLABS_API_KEY` を `.env` に書いてもOK
2. ペルソナ別設定 → 「**TTS エンジン**」を `elevenlabs` に変更
3. 「**ElevenLabs Voice ID**」に取得した voice_id を貼り付け

#### 4. 料金目安 (2026 年 5 月時点、最新は [ElevenLabs Pricing](https://elevenlabs.io/pricing) を参照)

| プラン | 月額 | クレジット/月 | カスタムボイス枠 | 商用 |
|---|---|---|---|---|
| **Free** | $0 | 10,000 | 3 (IVC) | 不可 |
| **Starter** | $5 | 30,000 | 10 (IVC) | 可 |
| **Creator** | $22 | 100,000 | 30 (IVC + PVC) | 可 |
| **Pro** | $99 | 500,000 | 160 | 可 |

クレジット消費レート (パック既定 `eleven_turbo_v2_5` の場合):

| プラン | 月の合成可能文字数 (turbo) | 100 文字発話に換算 |
|---|---|---|
| Free | 約 20,000 文字 | 約 200 発話 |
| Starter | 約 60,000 文字 | 約 600 発話 |
| Creator | 約 200,000 文字 | 約 2,000 発話 |

> モデル別 credit レート: `eleven_turbo_v2_5` (既定) と `eleven_flash_v2_5` は **0.5 credit/char**、`eleven_multilingual_v2` は **1 credit/char**。
> 月初リセット、未使用分は失効。

### Azure AI Speech のセットアップ

**漢字読みの精度を最重視するならこれ**。Microsoft の日本語 Neural TTS は固有名詞の読み分けが安定。Personal Voice 機能でゼロショット相当のクローンも可能 (申請制)。

#### 1. Azure サブスクリプションと Speech リソースの作成

1. https://portal.azure.com にサインイン (アカウント無ければ作成、無料枠あり)
2. 「リソースの作成」→ **Speech (AI + Machine Learning カテゴリ)** を選択
3. リソース名 (例: `saiverse-speech`)、サブスクリプション、リージョンを選ぶ
   - **Personal Voice を使う予定なら**: 対応リージョンは限定 (`westeurope` / `eastus2` / `southeastasia` / `westus2` 等)。日本リージョンは Personal Voice **非対応**なので注意
   - **Preset Neural TTS だけで OK** なら `japaneast` で問題なし (日本語コンテンツ向けレイテンシ最小)
4. 価格レベル: **F0 (無料、月 50 万文字まで)** で試す → 不足したら **S0 (従量)** にスケール
5. 作成完了後、リソース → 「**キーとエンドポイント**」メニューから:
   - `KEY 1` または `KEY 2` をコピー (= subscription key)
   - 「**場所/地域**」(= region 名、例: `japaneast`) を確認

#### 2. SAIVerse に登録

1. アドオン管理 → Voice TTS → デフォルトの「**Azure Speech Subscription Key**」(アコーディオン) に貼り付け
2. 「**Azure リージョン**」を上で確認したリージョン名に変更 (`japaneast` 等)
   - 環境変数 `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` を `.env` に書いてもOK
3. ペルソナ別設定 → 「**TTS エンジン**」を `azure_tts` に変更
4. 「**Azure 音声**」に preset voice 名を入れる (既定 `ja-JP-NanamiNeural`)
   - 主な日本語 voice: `ja-JP-NanamiNeural` (女性、自然) / `ja-JP-KeitaNeural` (男性、自然) / `ja-JP-AoiNeural` (女性、子供) / `ja-JP-DaichiNeural` (男性、ティーン) / `ja-JP-ShioriNeural` (女性、若年)
   - 全リスト: https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts#prebuilt-neural-voices

これで preset voice での発話が動くはず。voice 名の試聴は https://speech.microsoft.com/portal/voicegallery で可能。

#### 3. Personal Voice (クローン) を使う場合

> **要申請**: Personal Voice は責任ある AI 利用のため、Microsoft への利用申請 (eyes-on review) が必要。承認まで数日〜2 週間。https://aka.ms/customneural からアクセス申請を提出。

1. **Voice Talent (本人) Consent Form の準備**: Microsoft が指定する許諾文を本人が読み上げて録音する音声ファイル (英語または日本語)
2. **Speech Studio** (https://speech.microsoft.com) → **Custom Voice** → **Personal Voice** タブ
3. 新しい Speaker Profile 作成:
   - Voice Talent Consent (録音 wav) をアップロード
   - 参照音声 (3 秒以上、推奨 30 秒) をアップロード
4. 数十秒で Speaker Profile が生成 → **Speaker Profile ID** をコピー (UUID 形式、例: `12345678-abcd-...`)
5. SAIVerse のペルソナ別設定の「**Azure Personal Voice ID**」に貼り付け

**注意**: Personal Voice ID を入れると、`Azure 音声` の値は無視され、ベース voice は自動的に `DragonLatestNeural` (Personal Voice 用基本モデル) に切替わります。

#### 4. スタイル指定 (任意)

ペルソナ別設定の「**Azure 音声スタイル**」に値を入れると SSML の `<mstts:express-as style="...">` で包んで送信されます。voice によって使えるスタイルが違うので注意:

| スタイル例 | 説明 | 使える voice 例 |
|---|---|---|
| `cheerful` | 明るく | NanamiNeural, KeitaNeural |
| `sad` | 悲しげ | NanamiNeural |
| `chat` | カジュアル | NanamiNeural |
| `customerservice` | カスタマーサポート風 | NanamiNeural |
| `whispering` | ささやき | (limited) |
| `angry` | 怒った | (limited) |

各 voice の対応スタイル: https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts#voice-styles-and-roles

#### 5. 料金目安 (2026 年時点、最新は [Azure Pricing](https://azure.microsoft.com/pricing/details/ai-services/) を参照)

| 機能 | 単価 |
|---|---|
| **Standard Neural TTS** | $16/1M chars (約 ¥2,400/百万字) |
| **Personal Voice 出力** | $24/1M chars + $0.05/分 (audio output) |
| **Custom Neural Voice (training)** | 別途 (本格運用向け、本パックの範囲外) |

Free tier (F0): 月 50 万文字まで Neural TTS 無料、Personal Voice は別枠。個人試用なら F0 で当分回せる。

### 既存ペルソナのエンジン切替

既に GPT-SoVITS / Irodori で運用しているペルソナをクラウド系に切り替える場合、**ペルソナごとに「TTS エンジン」を変えれば OK**。一部だけ openai_tts、他は GPT-SoVITS、というハイブリッドも可能 (`registry.json` も併用可)。

### よくある問題

- **「最初の一文節だけ再生されて止まる」**: 内部の PCM byte alignment バグ修正済み。古いバージョンを使っている場合は最新へ pull
- **`API key not configured`**: addon UI のデフォルトセクション (アコーディオン展開) に貼り付ける場所を確認。ペルソナ別設定ではなくグローバル側
- **HTTP 401**: key の typo / 期限切れ / 課金未設定 (OpenAI は最低 $5 入金しないと API 動かない、Azure は F0 でも key 必須)
- **HTTP 403 (Azure)**: region の指定ミス。Azure Portal の「キーとエンドポイント」で表示される region 名と addon UI の値が一致しているか確認
- **HTTP 429**: レートリミット。1 回はリトライされるが続けば backoff、しばらく待つ
- **ElevenLabs HTTP 422**: voice_id がアカウントに存在しない、または別アカウントで作った Voice ID を貼っている
- **Azure Personal Voice 利用中の HTTP 400**: Speaker Profile ID が region と紐付いていない (作成リージョンと synthesize 呼び出しリージョンを一致させる)、または申請承認前 (eyes-on review 待ち)

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
- `lameenc>=1.5` — PCM → MP3 progressive エンコーダ(クライアント配信)
- `torchcodec>=0.10` — torchaudio.load バックエンド(Irodori で必要)

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

### 3. (オプション) Irodori-TTS の clone + 重み DL + 依存

```batch
python scripts\install_backends.py irodori
```

内部では:
- `external/Irodori-TTS/` へ shallow clone
- 上流 `requirements.txt` のうち推論に必須なものを pip install
- `Aratako/Irodori-TTS-500M-v2` / `Aratako/Semantic-DACVAE-Japanese-32dim` を HuggingFace からダウンロード(HF キャッシュに保存)

### 4. CUDA 版 torch の確認

```batch
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
```

`True` でなければ:
```batch
pip uninstall -y torch torchaudio torchvision
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121
```

### 5. 単体ロード確認

**GPT-SoVITS**:
```batch
python -c "import sys, os; sys.path.insert(0, r'%CD%\external\GPT-SoVITS'); sys.path.insert(0, r'%CD%\external\GPT-SoVITS\GPT_SoVITS'); os.chdir(r'%CD%\external\GPT-SoVITS'); from TTS_infer_pack.TTS import TTS, TTS_Config; TTS(TTS_Config('GPT_SoVITS/configs/tts_infer.yaml')); print('OK')"
```
`Loading Text2Semantic weights ...` 〜 `OK` まで流れれば成功。

**Irodori-TTS**:
```batch
python -c "import sys; sys.path.insert(0, r'%CD%\external\Irodori-TTS'); from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey; print('OK')"
```
`OK` が出れば import パスは通っている。実際のロードは初回発話時に行われる。

### 6. 参照音声配置・registry 編集

上記「セットアップ完了後の手動作業」と同じ。

## トラブルシューティング

セットアップや実行時の問題は [TROUBLESHOOTING.md](TROUBLESHOOTING.md) にまとめています。目次から該当トピックを探してください。代表的なハマりどころの例:

- setup.bat が途中で止まる / opencc / editdistance のビルドエラー
- CUDA が認識されない(GPT-SoVITS 依存で CPU 版 torch に上書きされる)
- Irodori 固有(`torchcodec` 未インストール、`dtype mismatch`、RTF が遅い、末尾ゴミ音声)
- モバイル Safari でタブが破棄される(dev mode 問題)
- 初回の音声が鳴らない(autoplay)

## 全バックエンド一括導入

```batch
setup.bat all
```

現時点でサポートしているのは GPT-SoVITS と Irodori-TTS の 2 つです。両方が inst 済みの状態でも、UI または `registry.json` で**ペルソナごとに使うエンジンを切り替えられます**。

## アンインストール

```batch
rmdir /S /Q external
del /Q voice_profiles\samples\_default\ref.wav
```
パック Python 依存は SAIVerse の `.venv` に残ります(他用途との共有のため)。完全削除は:
```batch
pip uninstall -y sounddevice soundfile opencc-python-reimplemented lameenc torchcodec
```
