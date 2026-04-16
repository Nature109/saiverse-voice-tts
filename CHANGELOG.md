# Changelog

日付は ISO 8601 形式(JST)。バージョン採番はまだ付与していないため、日付とマージコミットハッシュで識別。

## [Unreleased] — ドキュメント整備

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
- 初回発話(モデル未ロード): 話し始めまで 25〜30 秒 → **12 秒**
- 2回目以降(モデルロード済): → **0.5 秒**

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
- GPT-SoVITS: 1 発話あたり 10〜30 秒(後のストリーミング対応で体感 0.5 秒に短縮)

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
