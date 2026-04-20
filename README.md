# saiverse-voice-tts

SAIVerse 拡張パック。ペルソナが発話したテキストを、ペルソナごとに登録した参照音声でゼロショット音声クローン合成し、**バックエンドPC のスピーカーとクライアントブラウザの両方**で再生できます。Tailscale 越しのリモートでも動作。**2 回目以降は話し始めまで 5 秒以内** (環境により前後)。初回発話はモデルロードのため数十秒かかります。

## 特徴

- **ゼロショット音声クローン** — 3〜10秒の参照音声1つで、そのペルソナの声を再現
- **ストリーミング推論 + MP3 progressive 配信** — 合成完了を待たずチャンク単位でリアルタイム再生。iOS Safari 含むモバイルブラウザでも progressive 再生
- **クライアント側再生(Tailscale 対応)** — ブラウザ `<audio>` 要素で再生、リモート運用可能。アクティブなクライアントタブのみで鳴る自動判定あり
- **サーバー側再生(opt-in)** — バックエンド PC のスピーカー直接再生も同時に有効化可能(RDP 等で両端での音出し)
- **出力オーディオデバイス選択** — アドオン管理 UI からサーバー側出力デバイスを選択
- **SAIVerse アドオン基盤対応** — メッセージバブルに🔊再生ボタンが自動表示。ペルソナごとに自動発話の ON/OFF、参照音声の差し替え、モード切替が UI から可能
- **エンジン切替可能な設計** — 現在は GPT-SoVITS をメインに、Irodori-TTS を実験的サポート
- **全てローカル推論** — 外部APIサーバ不要。インターネット接続は初回の重みDL時のみ
- **Markdown/URI 自動除去** — ペルソナ応答中のリンクURLやマークアップは読み上げない

## クイックスタート(Windows)

SAIVerse 本体のセットアップ完了後、このリポジトリを `expansion_data/` 配下に配置し `setup.bat` を実行するだけです。

```batch
cd %USERPROFILE%\SAIVerse\expansion_data
git clone https://github.com/Nature109/saiverse-voice-tts.git
cd saiverse-voice-tts
setup.bat
```

`setup.bat` は以下を全自動で行います:

1. SAIVerse の `.venv` をアクティベート
2. パック依存(`numpy` / `sounddevice` / `soundfile` / `huggingface_hub` / `lameenc`)をインストール
3. `install_backends.py` で GPT-SoVITS を clone + 依存インストール + 重み DL
4. `torch` が CUDA 版であることを確認(そうでなければ `cu121` 版を自動再導入)
5. 音声デバイス一覧を表示、参照音声ファイルの有無をチェック

完了後、**参照音声の配置**だけ手動で:

1. `voice_profiles/samples/_default/ref.wav` に 3〜10秒の日本語音声 wav を置く（3秒以上10秒以内は必須）
2. `voice_profiles/registry.json` の `ref_text` を wav の書き起こしに合わせる
   (または SAIVerse の **アドオン管理 UI** から直接アップロード可能)

あとは SAIVerse 本体を通常通り起動するだけで、ペルソナの発話に合わせて音声が再生されます。

> **モバイル / Tailscale 運用での重要な注意**: Next.js の **dev mode (`npm run dev`)** では iOS Safari がタブを自動破棄する事象が観測されています。モバイルから利用する場合は **production build (`npm run build && npm run start`)** で SAIVerse を起動してください。

## 動作要件

| 項目 | 最小 | 推奨 |
|---|---|---|
| OS | Windows 10/11 or Linux | Windows 11 |
| Python | 3.10 | 3.10 |
| GPU | なし(CPU推論可、ただし非常に遅い) | NVIDIA RTX 3060以上 / VRAM 6GB以上 |
| CUDA | — | 12.1 以上 |
| ディスク | 8GB | 20GB(全エンジン導入時) |
| SAIVerse 本体 | アドオン基盤対応版 | 同上 |

GPT-SoVITS を CPU で動かすのは実用的ではありません(1発話数分)。GPU 必須と考えてください。

**本体バージョンについて**: バブルの🔊再生ボタン・アドオン管理 UI 連携・クライアント側再生を有効化するには、SAIVerse 本体が以下を提供している必要があります:

- `saiverse.addon_metadata` / `saiverse.addon_events` / `saiverse.addon_deps` / `saiverse.addon_config`
- `tools.context.get_active_message_id` + 配線済みの `set_active_message_id`
- `/api/addon/events` SSE エンドポイントと `addon_loader` の自動マウント機構
- `ui_extensions.client_actions` 宣言対応 + `play_audio` action executor(クライアント側再生を有効化する場合)
- Route Handler `/api/addon/[...path]` による `/stream` パススルー対応(progressive 再生を有効化する場合)

これらが存在しない旧バージョンでも、バックエンドPC のスピーカーから自動再生する基本機能のみ動作します。

## バックエンド選択

| エンジン | 話し始め(初回) | 話し始め(2回目以降) | 品質 | 推論速度(RTL) | ディスク | 備考 |
|---|---|---|---|---|---|---|
| **GPT-SoVITS**(既定・推奨) | 数十秒(モデルロード含む) | 5秒以内 | ◎ | 1.3〜1.5倍実時間 | 約4GB | ストリーミング対応、日本語実績多数 |
| Irodori-TTS | 未検証 | 未検証 | — | — | 約2GB | 実装済みだが本環境で未検証 |

> 初回発話では GPT-SoVITS がメモリにモデル(BERT / CNHuBERT / T2S / VITS、合計約4GB)をロードするため数十秒かかります。バックエンド再起動までの 2 回目以降は 5 秒以内で話し始めます(実測約 0.75 秒、余裕を持たせた目安)。

`setup.bat` はデフォルトで GPT-SoVITS を導入します。Irodori を試す場合は `setup.bat irodori` または `setup.bat all`。

## ファイル構成

```
saiverse-voice-tts/
├── README.md
├── SETUP.md                       ← 詳細セットアップ
├── TROUBLESHOOTING.md             ← トラブルシューティング(目次付き)
├── ARCHITECTURE.md                ← 内部アーキテクチャ
├── CHANGELOG.md                   ← 変更履歴
├── setup.bat                      ← Windows 向けワンクリックセットアップ
├── addon.json                     ← アドオン manifest (UI 設定項目/ボタン/client_actions)
├── api_routes.py                  ← FastAPI ルート (/audio/*, /stream, client_action_failed, audio-devices)
├── requirements.txt               ← パック固有の最小依存
├── scripts/install_backends.py    ← 上流 clone + 重み DL + pip install
├── external/                      ← .gitignore。各上流リポジトリを clone
│   ├── GPT-SoVITS/
│   └── Irodori-TTS/
├── tools/speak/
│   ├── schema.py                  ← speak_as_persona Tool
│   ├── text_cleaner.py            ← Markdown/URI 除去
│   ├── profiles.py                ← registry.json ローダ
│   ├── playback_worker.py         ← FIFO キュー + ストリーミング再生
│   ├── audio_stream.py            ← MP3 pub/sub 配信レジストリ
│   └── engine/
│       ├── base.py                ← TTSEngine 抽象
│       ├── gpt_sovits.py
│       └── irodori.py
├── playbooks/public/
│   └── sub_speak.json             ← 本体 sub_speak を上書きし、tts_speak ノード追加
├── voice_profiles/
│   ├── README.md                  ← プロファイル追加手順
│   ├── registry.json              ← ペルソナ毎の参照音声設定
│   └── samples/<persona_id>/ref.wav
└── config/default.json            ← エンジン共通設定
```

## 使い方

### アドオン管理 UI (推奨)

SAIVerse 画面のサイドバー → **アドオン管理** → **Voice TTS** から以下が設定できます:

| 項目 | 種類 | 既定 | 説明 |
|---|---|---|---|
| 自動発話 | toggle (ペルソナ別) | ON | ペルソナ発話のたびに TTS 合成を自動実行 |
| 参照音声 | file (ペルソナ別) | - | そのペルソナの声を再現するための wav (3〜10秒、必須) |
| 参照音声の書き起こし | text (ペルソナ別) | - | wav で話している内容 (句読点含め正確に) |
| サーバー側再生 | toggle | **OFF** | バックエンド PC のスピーカーから再生 |
| クライアント側再生 | toggle | **ON** | アクティブクライアントタブのブラウザから再生 |
| ストリーミング推論 | toggle | ON | 合成完了を待たずチャンク単位で逐次再生 |
| 出力オーディオデバイス | dropdown | `<default>` | サーバー側再生の出力先デバイス (`<default>` は OS 既定) |

### 参照音声の追加(CLI で手動編集する場合)

`voice_profiles/registry.json` にペルソナ ID をキーとしてエントリを追加:

```json
{
    "air_city_a": {
        "engine": "gpt_sovits",
        "ref_audio": "samples/air_city_a/ref.wav",
        "ref_text": "参照音声の正確な書き起こし。",
        "params": {
            "speed": 1.0,
            "temperature": 1.0,
            "top_k": 15,
            "text_split_method": "cut5"
        }
    },
    "_default": { ... }
}
```

ペルソナ ID にエントリが無ければ `_default` にフォールバックします。アドオン管理 UI からアップロードした場合は本体側のアドオンストレージに保存され、registry.json より UI 側の値が優先されます。詳細は [voice_profiles/README.md](voice_profiles/README.md) 参照。

### 再生方式の組み合わせ

| クライアント側再生 | サーバー側再生 | 動作 |
|---|---|---|
| ON (既定) | OFF (既定) | **Tailscale 含む全環境で推奨**。アクティブなブラウザタブから再生 |
| ON | ON | ブラウザと PC スピーカー両方で再生(バックエンド PC 手元で使うとき等) |
| OFF | ON | ブラウザで鳴らさず PC スピーカーのみ(ブラウザを開いていない運用) |
| OFF | OFF | 合成は実行、音は鳴らない(バブル再生ボタンで後から手動再生のみ) |

### Tailscale 運用について

**クライアント側再生**によりリモートブラウザで音声が鳴るようになりました:

- SAIVerse を **production build** で起動 (`npm run build && npm run start`) — dev mode では iOS Safari がタブ discard を起こす
- Tailscale 越しにスマホ等からアクセス
- 初回に画面を1回タップ (iOS Safari の autoplay unlock のため)
- ペルソナと会話 → ブラウザから音声が progressive に再生される

複数端末を同時に開いている場合、**最後に画面を触った端末**が自動的に「アクティブクライアント」として鳴らされます。ヘッダーの Radio アイコンで可視化されます。

## ライセンス

本パック自体は Apache 2.0。各エンジンの再配布は上流ライセンスに従ってください。

| エンジン | コード | 重み | 再配布 |
|---|---|---|---|
| GPT-SoVITS | MIT | MIT | ✅ |
| Irodori-TTS | MIT | MIT | ✅(要: ベース依存の個別再確認) |

配布物には `external/<repo>/LICENSE` を同梱してください。
