# saiverse-voice-tts

SAIVerse の拡張パック。ペルソナの発話テキストを、ペルソナ毎に登録した参照音声でゼロショット音声クローン合成し、バックエンドPCのスピーカーから自動再生します。

- **本体(SAIVerse)への改修は不要** — Tool + Playbook 差し替えのみで動作
- **3エンジン切替可能** — Qwen3-TTS (OSS) / GPT-SoVITS / Irodori-TTS
- **全てローカル推論** — 外部APIサーバ不要(各上流リポジトリを `external/` に clone して直接Python API呼び出し)
- **ノンブロッキング** — SEA の playbook 実行を止めずに裏で合成・再生

## ライセンス(再配布可否)

配布時にモデル重みを内包する想定のため、全エンジンの上流ライセンスを確認済み。

| エンジン | コード | 重み | 再配布 |
|---|---|---|---|
| Qwen3-TTS | Apache 2.0 | Apache 2.0 | ✅ 条件: ライセンス全文同梱 + 変更点明示 + NOTICE同梱 + 帰属表示 |
| GPT-SoVITS | MIT | MIT | ✅ 条件: ライセンス全文 + 著作権表示を同梱 |
| Irodori-TTS | MIT | MIT | ✅ 条件: ライセンス全文 + 著作権表示を同梱(※ベース依存 `llm-jp/llm-jp-3-150m`, `Aratako/Semantic-DACVAE-Japanese-32dim` の個別ライセンスを配布前に要再確認) |

**配布物には `external/<repo>/LICENSE` をそのまま同梱**することで条件を満たせます。

## インストール

1. リポジトリを配置:
   ```bash
   cd <SAIVerse>/expansion_data
   git clone <this-repo> saiverse-voice-tts
   cd saiverse-voice-tts
   pip install -r requirements.txt
   ```

2. 使用するエンジンをインストール(1つ以上):
   ```bash
   # 推奨(単発で最小依存)
   python scripts/install_backends.py qwen3_tts

   # GPT-SoVITS を使う場合
   python scripts/install_backends.py gpt_sovits

   # Irodori-TTS を使う場合
   python scripts/install_backends.py irodori

   # 3つ全部入れる場合
   python scripts/install_backends.py all
   ```
   スクリプトは以下を自動実行します:
   - `external/<name>/` に上流リポジトリを `git clone --depth 1`
   - 必要な場合 `pip install -e` でローカルパッケージ化
   - HuggingFace から学習済み重みを snapshot_download

3. 参照音声を配置:
   ```
   voice_profiles/
   ├── registry.json              # ← 編集
   └── samples/
       └── <persona_id>/ref.wav   # ← 3秒以上の日本語参照音声
   ```

4. `voice_profiles/registry.json` にペルソナ毎のエントリを追加:
   ```json
   {
     "air_city_a": {
       "engine": "qwen3_tts",
       "ref_audio": "samples/air_city_a/ref.wav",
       "ref_text": "参照音声の書き起こしテキスト",
       "params": { "temperature": 0.7 }
     },
     "_default": {
       "engine": "qwen3_tts",
       "ref_audio": "samples/_default/ref.wav",
       "ref_text": "デフォルト参照音声の書き起こし"
     }
   }
   ```

5. SAIVerse を起動:
   ```bash
   python main.py city_a
   ```
   起動時に Tool (`speak_as_persona`) とプレイブック (`sub_speak` 上書き版) が自動ロードされます。ペルソナが発話するたびに TTS が鳴ります。

## ディレクトリ構成

```
saiverse-voice-tts/
├── README.md
├── requirements.txt              ← 本パック固有の最小依存(numpy/sounddevice/huggingface_hub)
├── scripts/
│   └── install_backends.py       ← 上流のclone + 重みDL + pip install -e
├── external/                     ← .gitignoreで除外。各上流リポジトリをclone
│   ├── Qwen3-TTS/
│   ├── GPT-SoVITS/
│   └── Irodori-TTS/
├── tools/speak/
│   ├── schema.py                 ← speak_as_persona Tool本体
│   ├── profiles.py               ← registry.json loader + _default fallback
│   ├── playback_worker.py        ← FIFOキュー + ワーカースレッド + wav保存 + sounddevice再生
│   └── engine/
│       ├── __init__.py           ← create_engine() ファクトリ
│       ├── base.py               ← TTSEngine抽象 + SynthesisResult
│       ├── qwen3_tts.py          ← Qwen3TTSModel.generate_voice_clone() 呼び出し
│       ├── gpt_sovits.py         ← TTS_infer_pack.TTS.run() 呼び出し
│       └── irodori.py            ← InferenceRuntime.synthesize() 呼び出し
├── playbooks/public/
│   └── sub_speak.json            ← 本体sub_speakを上書きし、tts_speakノードを末尾に追加
├── voice_profiles/
│   ├── registry.json
│   └── samples/                  ← ペルソナID毎のwav
└── config/
    └── default.json              ← エンジン別設定(model_id, device, dtype等)
```

## 仕組み

### Tool: `speak_as_persona`
- SEA の playbook から呼ばれる
- 合成ジョブを内部キューへ投入して**即 return**(fire-and-forget)
- 裏のワーカースレッドが順次:
  1. `get_active_persona_id()` でペルソナ特定
  2. `registry.json` からプロファイル取得(未登録なら `_default`)
  3. エンジンを lazy-load(初回のみモデルロード)
  4. `synthesize(text, ref_audio, ref_text, params)`
  5. wav保存 (`~/.saiverse/user_data/voice/out/<uuid>.wav`)
  6. `sounddevice` で再生

### Playbook 差し替え
`playbooks/public/sub_speak.json` が本体の `builtin_data/playbooks/public/sub_speak.json` を上書きし、既存の compose → control_body の後に `speak_as_persona` ノードを追加します。

## 設定: `config/default.json`

| キー | 既定値 | 意味 |
|---|---|---|
| `default_engine` | `"qwen3_tts"` | プロファイルに `engine` が無い場合の既定 |
| `play_mode` | `"queue"` | FIFO順次再生(barge-in 将来拡張用) |
| `output_device` | `null` | sounddevice 出力デバイス番号(未指定=OS既定) |
| `gc_hours` | `24` | 生成wavの自動削除猶予 |
| `engines.qwen3_tts.model_id` | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | モデル |
| `engines.qwen3_tts.dtype` | `bfloat16` | `float16`/`bfloat16`/`float32` |
| `engines.gpt_sovits.config_yaml` | `null` | GPT-SoVITS `tts_infer.yaml` のパス(未指定=既定を使用) |
| `engines.irodori.checkpoint` | `Aratako/Irodori-TTS-500M-v2` | モデル |
| `engines.irodori.codec_repo` | `Aratako/Semantic-DACVAE-Japanese-32dim` | codec VAE |

## 制約(初版)

- **自動発話のみ**(ON/OFF切替なし)。発話は全て TTS される
- **バックエンドPCのスピーカー再生のみ**。Tailscale越しのスマホ再生は未対応(本体改修が必要で別リクエスト化)
- 参照音声は **registry.json 手書き**。UIは未実装
- プロファイル未登録ペルソナは `_default` にフォールバック。`_default` も無ければ TTS スキップ

## ライセンス

本パック自体は Apache 2.0。各エンジンの利用/再配布は上流のライセンスに従ってください(`external/<repo>/LICENSE` を同梱してください)。
