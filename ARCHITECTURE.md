# ARCHITECTURE

このドキュメントは saiverse-voice-tts の内部構造と設計判断を記述します。バグ修正・機能追加時の参考にしてください。

## 全体像

```
ペルソナ発話
   │
   ├─ SEA Playbook (sub_speak)
   │    └─ compose(LLM) → process_body → ★ tts_speak(speak_as_persona)
   │
   ▼
Tool: speak_as_persona(text)
   │
   ├─ clean_text_for_tts()        Markdown/URI除去
   ├─ get_active_persona_id()     persona_context から取得
   └─ enqueue_tts(text, id)       FIFOキューへ投入して即return(fire-and-forget)
   │
   ▼
Background worker thread (_TTSWorker._run)
   │
   ├─ profile = get_profile(persona_id)           registry.json からロード
   ├─ engine = create_engine(profile.engine)      初回のみ lazy load
   │
   ├─ [ストリーミング対応エンジン]
   │    └─ engine.synthesize_stream() → SynthesisChunk yield
   │          └─ sd.OutputStream.write(chunk)     チャンク毎に即時再生
   │          └─ 全チャンクを collect
   │
   └─ [非対応エンジン]
        └─ engine.synthesize() → SynthesisResult
              └─ sd.play(blocking=True)            一括再生
   │
   ▼
wav 保存 (~/.saiverse/user_data/voice/out/<job_id>.wav)
   │
   ▼
24時間 GC
```

## コンポーネント

### `tools/speak/schema.py`

Tool エントリポイント。`ToolSchema(name="speak_as_persona")` を公開し、SAIVerse の自動 Tool 発見機構に拾われる。

- `text` のみを引数に取る(persona_id は context 経由、message_id は将来本体が context に注入する予定)
- `clean_text_for_tts()` で前処理
- `enqueue_tts(cleaned, persona_id)` で即 return
- 戻り値: `{content: "", metadata: {voice_tts: {status, job_id, persona_id}}}`

**設計判断**: 同期版は意図的に提供していない。Playbook がSEA 実行をブロックしないよう常に非同期キュー投入。

### `tools/speak/text_cleaner.py`

Markdown と SAIVerse URI を除去する純関数モジュール。

| パターン | 処理 |
|---|---|
| `[text](url)` | `text` のみ残す |
| `![alt](url)` | 全て削除 |
| `[text][ref]` | `text` のみ残す |
| `**bold**` / `__bold__` | 中身のみ |
| `*italic*` / `_italic_` | 中身のみ |
| `` `code` `` | 中身のみ |
| `~~strike~~` | 中身のみ |
| `# heading` | `#` 記号削除 |
| `- list` / `* list` / `+ list` | マーカー削除 |
| `> quote` | `>` 削除 |
| `https://...`, `saiverse://...`, etc | 削除 |
| 3個以上の空行 | 2個に圧縮 |

**設計判断**: TTS エンジンに渡す前に一段階変換する。Building 履歴に残るテキスト自体は Markdown のままなので、チャット UI の見た目は壊れない。

### `tools/speak/profiles.py`

`voice_profiles/registry.json` をロードして persona_id → profile dict を返す。

- 初回読込のみキャッシュ(プロセス生存中は再読込しない)
- `ref_audio` の相対パスを pack root からの絶対パスに解決
- `persona_id` が registry にない場合は `_default` にフォールバック
- `_default` も無ければ `None` → TTS スキップ(ログ出力のみ)

**設計判断**: 参照音声の DL/配置はユーザー作業なので、無い場合はエラーではなく警告にとどめる。

### `tools/speak/playback_worker.py`

`_TTSWorker` シングルトン。FIFO `queue.Queue` + 単一ワーカースレッド + `sounddevice` 再生。

主要責務:
- キュー管理(`enqueue()` / `_run()`)
- 初回のみエンジン lazy load(`_get_engine()`)
- ストリーミング / 非ストリーミング切替(`_process()`)
- wav 保存(`_save_wav()`)
- 古い wav の GC(`_gc_old_files()`)
- プロセス終了時の graceful shutdown(`atexit`)

#### ストリーミング再生の実装(`_play_streaming()`)

```python
stream = None
collected: list[np.ndarray] = []
for chunk in engine.synthesize_stream(text=..., ...):
    if stream is None:
        # 初回チャンク到達 = サンプルレートが判明した瞬間
        stream = sd.OutputStream(samplerate=chunk.sample_rate, channels=1, device=...)
        stream.start()
    stream.write(chunk.audio.astype(np.float32))
    collected.append(chunk.audio)
stream.stop(); stream.close()
# 全チャンク結合 → wav 保存(履歴用)
```

**設計判断**: `sd.play()` ではなく `sd.OutputStream` を使うのは、合成と同時進行で書き込みたいため。`sd.play()` は一括バッファ受取が前提。

**失敗時の自動フォールバック**: ストリーミングが例外で失敗したら `_play_streaming()` が False を返し、`_process()` が通常の `engine.synthesize()` + `sd.play()` にフォールバック。

### `tools/speak/engine/`

`TTSEngine` 抽象クラスと具体実装。

#### `base.py`
- `TTSEngine`: 抽象基底、`synthesize()` 必須、`synthesize_stream()` はデフォルト実装(単一チャンクをラップ)
- `supports_streaming: bool`: クラスレベルフラグ
- `SynthesisResult`: 一括合成の結果(audio, sample_rate, duration_ms)
- `SynthesisChunk`: ストリーミング単位(audio, sample_rate)

#### `gpt_sovits.py`
最も完成度の高いエンジン。`supports_streaming = True`。

**難所とその対処**:
1. **cwd 依存**: GPT-SoVITS は `pretrained_models/...` を相対パスで開く。`_cwd(_EXTERNAL_REPO)` コンテキストマネージャでロード・推論両方を repo 直下で実行。
2. **`tools/` 名前空間衝突**: GPT-SoVITS 内部の `from tools.audio_sr import ...` が SAIVerse の `tools/` パッケージと衝突。`_shadowed_tools_namespace()` で import 中だけ `sys.modules['tools']` を退避。
3. **ストリーミングパラメータ**: `streaming_mode=True` + `parallel_infer=False` の組み合わせが必要(SoVITS V3/V4 は自動で return_fragment にフォールバック)。

#### `irodori.py`
未検証。`InferenceRuntime.synthesize()` のラッパスケルトン。実験的サポート。

## データフロー詳細

### 初回発話

```
t=0.0  persona → speak_as_persona(text)
t=0.01 enqueue → return
t=0.01 worker: profile lookup
t=0.02 worker: engine.synthesize_stream() 呼び出し
t=0.02 → lazy_load (10〜20秒): BERT / CNHuBERT / T2S / VITS ロード
t=20.0 ref_audio 埋め込み計算 (1〜2秒)
t=22.0 第一チャンク yield
t=22.0 sd.OutputStream 開始 → 再生開始
t=22.5 ← ★話し始めが聞こえるタイミング
t=N    最終チャンク yield + stream.stop()
t=N    wav 保存
```

### 2回目以降

```
t=0.0  enqueue
t=0.01 worker: engine 取得(キャッシュ済み)
t=0.01 engine.synthesize_stream()
t=0.01 ref_audio キャッシュヒット(同一ペルソナなら set_ref_audio スキップ)
t=0.5  第一チャンク yield → 再生開始 ← ★話し始め
t=N    完了
```

## Playbook 統合

`playbooks/public/sub_speak.json` で本体の `builtin_data/playbooks/public/sub_speak.json` を上書き。

本体オリジナルは `compose(LLM) → process_body(control_body)` の2ノード構成。拡張パック版はこれに `tts_speak(speak_as_persona)` を末尾追加した3ノード構成。

SAIVerse の playbook 優先順(`user_data > expansion_data > builtin_data`)により、このパックが `expansion_data/` に配置されている限り本体オリジナルを上書きします。

## 設計上の制約と拡張方針

### 現状の制約

1. **バックエンド PC のスピーカーからのみ再生**: `sounddevice` がサーバプロセスで音を出すため、リモートクライアントでは聞こえない
2. **自動再生の ON/OFF トグル無し**: 常に再生する
3. **ペルソナ単位の音量/音響調整無し**: `speed` 等は調整可だが、ボリュームはアプリ外
4. **FIFO 直列再生のみ**: 複数ペルソナの同時発話は順番待ちになる
5. **transformers バージョン制約**: GPT-SoVITS は `transformers>=4.43,<=4.50` を要求するため、別のエンジンを追加する際はこの範囲を尊重する必要がある

### 今後の拡張(本体アドオンフレームワーク連携待ち)

本体側で以下が整備され次第対応予定:

- `persona_context` に `message_id` 注入 → メッセージ ID と wav ファイルの紐付け
- `/api/addon/saiverse-voice-tts/audio/<message_id>` エンドポイント → リモート再生
- `/api/addon/saiverse-voice-tts/audio/<message_id>/stream` エンドポイント → ストリーミング配信
- SSE `addon_event` → フロントエンドの「音声準備完了」通知

拡張パック側で追加実装予定の疑似コードは [api_routes.py.stub](tools/speak/api_routes.py.stub) 参照(本体仕様確定後に有効化)。

## 参考

- [GPT-SoVITS upstream](https://github.com/RVC-Boss/GPT-SoVITS)
- [Irodori-TTS upstream](https://github.com/Aratako/Irodori-TTS)
- [SAIVerse 本体 Tool 仕様](../../CLAUDE.md) — 拡張 Tool 作成ガイド
