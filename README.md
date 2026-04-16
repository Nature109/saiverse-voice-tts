# saiverse-voice-tts

SAIVerse 拡張パック。ペルソナが発話したテキストを、ペルソナごとに登録した参照音声でゼロショット音声クローン合成し、バックエンドPCのスピーカーから**話し始め 0.5秒以内**で自動再生します。

- **本体(SAIVerse)への改修は不要** — Tool + Playbook 差し替えのみで動作
- **ストリーミング推論対応** — 合成完了を待たずチャンク単位でリアルタイム再生
- **3エンジン切替可能** — GPT-SoVITS(推奨)/ Qwen3-TTS / Irodori-TTS
- **全てローカル推論** — 外部APIサーバ不要
- **Markdown/URI 自動除去** — ペルソナ応答中のリンクURLなどは読み上げない

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
2. パック依存(`numpy` / `sounddevice` / `soundfile` / `huggingface_hub`)をインストール
3. `install_backends.py` で GPT-SoVITS を clone + 依存インストール + 重み DL
4. `torch` が CUDA 版であることを確認(そうでなければ `cu121` 版を自動再導入)
5. 音声デバイス一覧を表示、参照音声ファイルの有無をチェック

完了後、**参照音声の配置**だけ手動で:

1. `voice_profiles/samples/_default/ref.wav` に 3秒以上の日本語音声 wav を置く
2. `voice_profiles/registry.json` の `ref_text` を wav の書き起こしに合わせる

あとは SAIVerse 本体を通常通り起動するだけで、ペルソナの発話に合わせて音声が再生されます。

## 動作要件

| 項目 | 最小 | 推奨 |
|---|---|---|
| OS | Windows 10/11 or Linux | Windows 11 |
| Python | 3.10 | 3.10 |
| GPU | なし(CPU推論可、ただし非常に遅い) | NVIDIA RTX 3060以上 / VRAM 6GB以上 |
| CUDA | — | 12.1 以上 |
| ディスク | 8GB | 20GB(全エンジン導入時) |

GPT-SoVITS を CPU で動かすのは実用的ではありません(1発話数分)。GPU 必須と考えてください。

## バックエンド選択

| エンジン | 話し始め(2回目以降) | 品質 | 推論速度(RTL) | ディスク | 備考 |
|---|---|---|---|---|---|
| **GPT-SoVITS**(推奨) | 0.5秒 | ◎ | 1.3〜1.5倍実時間 | 約4GB | ストリーミング対応、日本語実績多数 |
| Qwen3-TTS | 〜30秒 | ◎ | リアルタイム | 約4GB | `generate_voice_clone` API、ストリーミング未対応 |
| Irodori-TTS | 未検証 | — | — | 約2GB | 実装済みだが本環境で未検証 |

**初版は GPT-SoVITS のみを setup.bat のデフォルトにしてあります**。他のエンジンを試す場合は `setup.bat all` や `setup.bat qwen3_tts` で切替できます。

## ファイル構成

```
saiverse-voice-tts/
├── README.md
├── SETUP.md                       ← 詳細セットアップ / トラブルシューティング
├── ARCHITECTURE.md                ← 内部アーキテクチャ
├── CHANGELOG.md                   ← 変更履歴
├── setup.bat                      ← Windows 向けワンクリックセットアップ
├── requirements.txt               ← パック固有の最小依存
├── scripts/install_backends.py    ← 上流 clone + 重み DL + pip install
├── external/                      ← .gitignore。各上流リポジトリを clone
│   ├── Qwen3-TTS/
│   ├── GPT-SoVITS/
│   └── Irodori-TTS/
├── tools/speak/
│   ├── schema.py                  ← speak_as_persona Tool
│   ├── text_cleaner.py            ← Markdown/URI 除去
│   ├── profiles.py                ← registry.json ローダ
│   ├── playback_worker.py         ← FIFO キュー + ストリーミング再生
│   └── engine/
│       ├── base.py                ← TTSEngine 抽象
│       ├── gpt_sovits.py
│       ├── qwen3_tts.py
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

### 参照音声の追加(ペルソナ個別)

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

ペルソナ ID にエントリが無ければ `_default` にフォールバックします。詳細は [voice_profiles/README.md](voice_profiles/README.md) 参照。

### 自動再生の ON/OFF

config 上でのトグルは現状未実装(常に自動再生)。将来的にはペルソナ単位で設定可能にする予定(本体側のアドオン仕様待ち)。

### Tailscale 運用について

**現状、バックエンド PC のスピーカーからのみ再生**されます。Tailscale 経由でリモートから接続したクライアント側では音が鳴りません。本体側のアドオンフレームワーク(計画中)経由でクライアント配信できるようにする改修を依頼済みです。

## ライセンス

本パック自体は Apache 2.0。各エンジンの再配布は上流ライセンスに従ってください。

| エンジン | コード | 重み | 再配布 |
|---|---|---|---|
| Qwen3-TTS | Apache 2.0 | Apache 2.0 | ✅ |
| GPT-SoVITS | MIT | MIT | ✅ |
| Irodori-TTS | MIT | MIT | ✅(要: ベース依存の個別再確認) |

配布物には `external/<repo>/LICENSE` を同梱してください。
