# voice_profiles/

ペルソナ ID と参照音声(ref wav)の対応表を定義するディレクトリ。

## ディレクトリ構成

```
voice_profiles/
├── README.md            ← このファイル
├── registry.json        ← ペルソナ ID → プロファイル対応表
└── samples/
    ├── _default/
    │   └── ref.wav      ← デフォルト参照音声(どのペルソナIDにも無い時のフォールバック)
    ├── <persona_id_1>/
    │   └── ref.wav
    └── <persona_id_2>/
        └── ref.wav
```

## registry.json の書き方

```json
{
    "_default": {
        "engine": "gpt_sovits",
        "ref_audio": "samples/_default/ref.wav",
        "ref_text": "参照音声の正確な書き起こしテキスト。",
        "params": {
            "speed": 1.0,
            "temperature": 1.0,
            "top_k": 15,
            "top_p": 1.0,
            "text_split_method": "cut5"
        }
    },
    "Yui_city_a": {
        "engine": "gpt_sovits",
        "ref_audio": "samples/Yui_city_a/ref.wav",
        "ref_text": "結衣ペルソナの参照音声の書き起こし。",
        "params": {
            "speed": 1.05
        }
    }
}
```

### フィールド

| フィールド | 必須 | 説明 |
|---|---|---|
| `engine` | 必須 | `gpt_sovits`(推奨) / `irodori`(実験的) |
| `ref_audio` | 必須 | `samples/` 以下の相対パス(絶対パスも可) |
| `ref_text` | 必須 | `ref_audio` の**正確な**書き起こし。句読点まで合わせると品質向上 |
| `params` | 任意 | エンジン別の生成パラメータ |

### `params` に指定できる項目(エンジン別)

#### gpt_sovits
| キー | 既定値 | 説明 |
|---|---|---|
| `speed` | 1.0 | 話速(0.5〜2.0) |
| `top_k` | 15 | サンプリング |
| `top_p` | 1.0 | サンプリング |
| `temperature` | 1.0 | ランダム性 |
| `text_split_method` | `cut5` | テキスト分割方式(`cut1` `cut2` `cut3` `cut4` `cut5`) |
| `overlap_length` | 2 | ストリーミング時のチャンク間オーバーラップ |
| `min_chunk_length` | 16 | ストリーミング最小チャンク長(semantic token 数) |
| `fixed_length_chunk` | false | 固定長チャンク(true で速度優先・品質低下) |

## 参照音声の準備ガイド

### 推奨スペック
- **長さ**: 3〜10秒(短すぎると声紋抽出失敗、長すぎるとロード時間増)
- **サンプリングレート**: 16kHz 以上、24kHz/48kHz 推奨
- **チャンネル**: モノラル(ステレオは自動で mono に落ちる場合あり)
- **形式**: wav(PCM 16bit / 24bit / 32bit float)
- **内容**:
  - 目標の話者の素のトーンでの日本語発話
  - 背景雑音・BGM なし
  - 口の中の音(リップノイズ)少なめ
  - 感情の起伏が極端でない(フラット寄り推奨、感情は合成時のテキストと参照音声の相互作用で乗る)

### 書き起こしの書き方
- **正確に**: 言い間違い・助詞の脱落・語尾の曖昧さまで含めて聞こえた通りに
- **句読点を含める**: 音声のポーズに合わせて `、` `。` を入れる
- 英単語や固有名詞は原語で(「Claude」→「クロード」等、実際に音声で言っている通りに)

### 既存音源からの切り出し例(ffmpeg)

```bash
# 元動画から 10秒切り出し、16kHz mono wav に変換
ffmpeg -i source.mp4 -ss 00:01:23 -t 10 -ac 1 -ar 24000 samples/Yui_city_a/ref.wav
```

## ペルソナ ID の確認方法

SAIVerse の DB からペルソナ一覧を取得:

```python
import sqlite3
conn = sqlite3.connect(r'C:\Users\<user>\.saiverse\user_data\database\saiverse.db')
for row in conn.execute('SELECT PERSONA_ID, DISPLAY_NAME FROM ai'):
    print(row)
```

表示される `PERSONA_ID`(例: `Yui_city_a`)を `registry.json` のキーに使用。

## 動作確認

プロファイル追加後、SAIVerse を再起動して該当ペルソナに話しかける。正しく認識されていれば以下のログが出る:

```
speak_as_persona enqueued: persona=Yui_city_a job=...
Loading GPT-SoVITS TTS pipeline     ← 初回のみ
TTS first chunk ready after 0.53s (job=...)
TTS streamed wav saved: ...\voice\out\<job_id>.wav
```

`No voice profile for persona_id=Xxx (and no _default); skipping TTS.` が出たら registry.json のキー名を再確認(ペルソナ ID と完全一致が必要)。

## よくある失敗

- `ref_text` が wav の実際の発声と微妙に違う → 合成音声が不安定になる / 違う話者に聞こえる
- `ref_audio` のパスタイポ → `_default` にフォールバックするので気付きにくい。ログで `No voice profile` が出ていなければ読み込めている
- ステレオ wav の片チャンネルのみ使用される → mono に変換を推奨
- サンプリングレート不一致 → GPT-SoVITS は内部で resample するので問題ないが、24kHz/32kHz 推奨
