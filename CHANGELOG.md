# Changelog

日付は ISO 8601 形式(JST)。バージョン採番はまだ付与していないため、日付とマージコミットハッシュで識別。

## [Unreleased]

### アドオン UI トグルを実際に尊重するよう接続(experiment/addon-config-consume)

SAIVerse 本体に `saiverse.addon_config.get_params` / `is_addon_enabled`(コミット `56c344a`)が追加されたため、拡張パック側で読み取って反映するようにした。

- `tools/speak/playback_worker.py`:
  - `_get_effective_params(persona_id)` を新設。本体 `saiverse.addon_config.get_params` を優先し、未提供時は `config/default.json` の既存値にフォールバック
  - `_process()` は config ではなく effective params を見て `streaming` / `server_side_playback` を判定
  - 有効 params のデバッグログを追加
  - `get_effective_params` を公開関数として export
- `tools/speak/schema.py`:
  - enqueue 前に `_enabled` / `auto_speak` をチェックし、OFF のときは即 return
  - 戻り値の `status` に `skipped_addon_disabled` / `skipped_auto_speak_off` を追加

これで UI の「自動発話」「サーバー側再生」「ストリーミング推論」トグルおよびペルソナ別上書きがランタイムに反映される。本体 API が無い環境では従来通り `config/default.json` の値で動作。

### SAIVerse 本体アドオン基盤への連携(experiment/addon-integration)

SAIVerse 本体の `feature/memory-notes-and-organize` ブランチで実装されたアドオン基盤(`ab22842`)に対応。

- `addon.json` 新規作成(マニフェスト):
  - `name` / `display_name` / `description` / `version`
  - `params_schema`: `auto_speak` (persona設定可)、`server_side_playback`、`streaming` の3つのトグル
  - `ui_extensions.bubble_buttons`: フロント側がメッセージバブル内に「音声を再生」ボタンを自動追加。`metadata_key=audio_path` が存在するときのみ表示
- `api_routes.py` 新規作成(旧 `api_routes.py.stub` を削除):
  - `GET /audio/{message_id}` 完成wavを `FileResponse` で配信
  - `GET /audio/{message_id}/stream` 合成進行中のチャンクを HTTP Chunked Transfer で配信
  - 認証は本体 `saiverse.addon_deps.get_manager` を `Depends()` で差し込み
- `tools/speak/audio_stream.py` 新規作成:
  - スレッドセーフな FIFO Queue レジストリ
  - `open_stream` / `push_chunk` / `close_stream` API
  - 0xFFFFFFFF サイズヘッダの WAV プレフィックスでブラウザ逐次再生可
- `tools/speak/playback_worker.py` 改修:
  - `_get_active_message_id()` で `tools.context.get_active_message_id` を取得
  - 合成完了時に `saiverse.addon_metadata.set_metadata` と `saiverse.addon_events.emit_addon_event` を呼び出し
  - `_Job` に `message_id` フィールド追加(enqueue 時点で capture)
  - `_play_streaming` は `audio_stream.open_stream/push_chunk/close_stream` を並行呼び出しし、同じ音声をサーバ再生と HTTP 配信の両方に流す
  - `server_side_playback=False` のときサーバ側再生をスキップ(HTTP 配信のみ)
- `config/default.json` に `server_side_playback: true` を追加

本体側の `addon_metadata` / `addon_events` / `addon_deps` モジュールが未提供の場合は全て警告ログのみで安全に無効化される(下位互換)。

### Qwen3-TTS エンジン削除

ストリーミング非対応で話し始めに 30 秒程度かかり実用性に欠けるため、メインエンジンから外しました。

- `tools/speak/engine/qwen3_tts.py` 削除
- `tools/speak/engine/__init__.py` から qwen3_tts ディスパッチ削除
- `scripts/install_backends.py` から qwen3_tts spec 削除、既定を gpt_sovits に
- `config/default.json` から qwen3_tts 設定ブロック削除、`default_engine` を gpt_sovits に
- `playback_worker.py` の既定エンジンフォールバックを gpt_sovits に
- README / SETUP / ARCHITECTURE / voice_profiles/README / requirements / setup.bat の Qwen3-TTS 記述を整理
- 履歴は残っているので、必要な場合は過去コミット `ca93ffb` 以前を参照可能

### ドキュメント整備

- README / SETUP / ARCHITECTURE / CHANGELOG を整備
- Windows 向けワンクリックセットアップ `setup.bat` を追加
- `install_backends.py` に opencc 自動除外、pre_install_pip、extra_dirs フィールドを追加
  (Windows で GPT-SoVITS セットアップが opencc ビルド失敗で止まる問題を解消)
- `requirements.txt` に soundfile を追加

## 2026-04-16 — ストリーミング合成と Markdown 除去

Merge: `44a7d42`
Feature: `fcd4e55`

発話テキスト → 音声再生までのレイテンシを大幅に短縮。

### 新機能
- GPT-SoVITS のストリーミング推論(`streaming_mode=True, parallel_infer=False`)に対応
- チャンク単位で即時再生(`sd.OutputStream` ベース)
- ストリーミング失敗時は非ストリーミング合成に自動フォールバック
- ペルソナ発話内の Markdown リンク・画像・強調・見出し・`saiverse://` URI などを TTS 前に除去する `text_cleaner.py` を追加

### 性能
- 初回発話(モデル未ロード): 話し始めまで 25〜30 秒 → **約 12 秒**(依然ロード時間が支配)
- 2回目以降(モデルロード済): → **約 1 秒**(実測 0.5〜1 秒程度、環境により変動)

### 変更ファイル
- `tools/speak/engine/base.py`: `SynthesisChunk` / `supports_streaming` / `synthesize_stream()` デフォルト実装
- `tools/speak/engine/gpt_sovits.py`: `supports_streaming=True`、`synthesize_stream()` 実装、`_build_inputs` リファクタ
- `tools/speak/playback_worker.py`: `_play_streaming()` 新設、初回チャンク到達時刻ログ
- `tools/speak/schema.py`: `clean_text_for_tts()` 前処理
- `tools/speak/text_cleaner.py`: 新規
- `config/default.json`: `streaming: true` 既定値

## 2026-04-16 — GPT-SoVITS 実用化

Merge: `a972124`
Feature: `ddee6f4`

Qwen3-TTS の合成時間が 2 分と実用性に欠けたため、GPT-SoVITS を主エンジンに採用。

### 新機能
- `engine/gpt_sovits.py`: GPT-SoVITS を SAIVerse プロセス内から直接呼び出せるよう実装
  - cwd を `external/GPT-SoVITS/` に一時変更する contextmanager
  - SAIVerse `tools/` パッケージとの名前空間衝突を回避する `sys.modules` シャドウイング
- `scripts/install_backends.py`:
  - `weights_local_dir` の `external/` プレフィックス修正
  - `pip_install_requirements` 仕様を追加(clone 後に requirements.txt を自動インストール)
- `voice_profiles/registry.json`: `_default.engine` を `gpt_sovits` に、GPT-SoVITS 推論パラメータを追加

### 性能
- Qwen3-TTS(1.7B): 1 発話あたり約 2 分
- GPT-SoVITS: 1 発話あたり 10〜30 秒(後のストリーミング対応で体感的な話し始めは約 1 秒まで短縮)

## 2026-04-16 — Qwen3-TTS を Base バリアントに修正

Merge: `acab51b`

初期実装で誤って `Qwen3-TTS-12Hz-1.7B-CustomVoice` を使っていたため、ゼロショット音声クローンが不可能だった(CustomVoice は事前登録話者専用で `generate_custom_voice(speaker=...)` を要求)。

### 修正
- モデルを `Qwen3-TTS-12Hz-1.7B-Base` に切替(`generate_voice_clone(ref_audio=..., ref_text=...)` を使用)
- `config/default.json` の `device` を `"auto"` → `"cuda:0"` に明示化(auto で CPU フォールバックが発生していた)
- `dtype` を `float16` → `bfloat16` に変更(RTX 4080 推奨、数値安定性向上)
- `output_device: 1` を設定し、リモートデスクトップ越し再生に対応
- `generate_voice_clone` 呼び出しに生成パラメータ(max_new_tokens / do_sample / top_k / top_p / temperature / repetition_penalty)を追加
- `voice_profiles/registry.json` の `_default.ref_text` をサンプル参照音声の内容に合わせて更新

## Initial — 初期実装

Commit: `694d272`

- ディレクトリ構造と Tool / Engine / Worker / Profile の骨子
- Qwen3-TTS エンジン実装(CustomVoice 版、後に Base 版に修正)
- GPT-SoVITS / Irodori-TTS エンジンのスケルトン
- `playbooks/public/sub_speak.json` で本体 sub_speak を上書きし `tts_speak` ノードを追加
- `scripts/install_backends.py` で各エンジンの自動導入
