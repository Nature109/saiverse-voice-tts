"""ユーザー読み方辞書(発音上書き)。

## 目的

GPT-SoVITS / Irodori-TTS の g2p (grapheme-to-phoneme) が固有名詞・専門語を
誤読する場合に、TTS エンジンに渡す**直前**にテキストを文字列置換する。

例: "まはー" を MeCab が「ま+は(助詞)+ー」と誤分割して `mawaa` 読みに
してしまう問題に対し、辞書で "まはー" → "マハー" と置換すれば
カタカナの「ハ」は助詞解釈されないため `mahā` ≈ `mahaa` で読まれる。

## 適用範囲

ペルソナの応答テキストを TTS エンジンに渡す直前のフィルタ。チャット UI
表示テキストや SAIMemory 保存テキストには影響しない(text_cleaner.py と
同じレイヤー)。

## グローバル辞書のソース

「全ペルソナ共通」の辞書は以下 2 ソースのマージ結果:

1. ``voice_profiles/pronunciation_dict.json`` (ファイル辞書、CLI 編集向け)
   - ローカル版が無ければ ``.template`` から初回コピー
2. アドオン管理 UI の ``pronunciation_dict`` (DB 保存、GUI 編集向け)
   - host 本体の ``saiverse.addon_config.get_params`` 経由で取得
   - ``addon.json`` の params_schema で persona_configurable=false で定義

同一キーに対しては **UI > ファイル** で UI の値が優先される。
ファイル辞書はキャッシュするが、UI 辞書は呼び出しごとに fresh で取得する
(ユーザーが UI で編集した直後でも反映される)。

## ペルソナ別オーバーライド

``voice_profiles/registry.json`` のペルソナエントリに ``pronunciation_dict``
キーを追加すれば、そのペルソナだけ別の読み方を持たせることが可能。
適用順序は **persona override → global (UI ∪ file) → そのまま**。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

_PACK_ROOT = Path(__file__).resolve().parent.parent.parent
_DICT_PATH = _PACK_ROOT / "voice_profiles" / "pronunciation_dict.json"
_DICT_TEMPLATE_PATH = _PACK_ROOT / "voice_profiles" / "pronunciation_dict.json.template"
_ADDON_NAME = "saiverse-voice-tts"

# (key, value) の長さ降順ソート済みリスト。ファイル辞書のキャッシュのみ。
# UI 辞書は DB 直読みなのでキャッシュしない (UI 編集後すぐ反映するため)。
_cached_file_entries: Optional[List[Tuple[str, str]]] = None
_lock = Lock()


def _materialize_if_missing() -> None:
    """ローカル版が無ければ template から初回コピー (first-run)。"""
    if not _DICT_PATH.exists() and _DICT_TEMPLATE_PATH.exists():
        try:
            _DICT_PATH.write_text(
                _DICT_TEMPLATE_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            LOGGER.info(
                "Materialized %s from %s (first run).",
                _DICT_PATH.name, _DICT_TEMPLATE_PATH.name,
            )
        except Exception as exc:
            LOGGER.warning(
                "Failed to materialize %s from template: %s",
                _DICT_PATH, exc,
            )


def _normalize_entries(raw: object) -> List[Tuple[str, str]]:
    """JSON で読んだ object を (key, value) の長さ降順リストに正規化。

    - dict 以外は空
    - 非文字列キー、空文字キーは除外
    - value は str() で統一
    - キーの長さで降順ソート(長い match 優先のため)
    """
    if not isinstance(raw, dict):
        return []
    entries: List[Tuple[str, str]] = []
    for k, v in raw.items():
        if not isinstance(k, str) or not k:
            continue
        # メタデータ的な _comment 等のキーは無視
        if k.startswith("_"):
            continue
        entries.append((k, str(v) if v is not None else ""))
    entries.sort(key=lambda kv: -len(kv[0]))
    return entries


def _load_file_entries() -> List[Tuple[str, str]]:
    """ファイル辞書をロード(キャッシュあり)。"""
    global _cached_file_entries
    if _cached_file_entries is not None:
        return _cached_file_entries
    with _lock:
        if _cached_file_entries is not None:
            return _cached_file_entries
        _materialize_if_missing()
        source = _DICT_PATH if _DICT_PATH.exists() else _DICT_TEMPLATE_PATH
        if not source.exists():
            _cached_file_entries = []
            return _cached_file_entries
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.warning(
                "Failed to parse pronunciation dict %s: %s", source, exc
            )
            _cached_file_entries = []
            return _cached_file_entries
        _cached_file_entries = _normalize_entries(data)
        LOGGER.debug(
            "Loaded %d file pronunciation dict entries from %s",
            len(_cached_file_entries), source.name,
        )
    return _cached_file_entries


def _load_ui_entries() -> List[Tuple[str, str]]:
    """アドオン管理 UI で設定されたグローバル辞書をロード (キャッシュなし)。

    saiverse 本体が無い環境 (ユニットテスト等) や、addon_config がまだ初期化
    されていない場合は空リストを返す (=ファイル辞書のみで動作する)。
    """
    try:
        from saiverse.addon_config import get_params  # type: ignore
        params = get_params(_ADDON_NAME)
        pd = params.get("pronunciation_dict")
        if isinstance(pd, dict) and pd:
            return _normalize_entries(pd)
    except Exception as exc:
        LOGGER.debug("addon_config unavailable for global dict: %s", exc)
    return []


def _load_global_entries() -> List[Tuple[str, str]]:
    """グローバル辞書 = UI 辞書 ∪ ファイル辞書 (UI が同一キーで優先)。

    長さ降順でソートして返す (長い match 優先 → 部分一致による誤置換防止)。
    """
    file_entries = _load_file_entries()
    ui_entries = _load_ui_entries()
    if not ui_entries:
        return file_entries  # 高速パス: UI 設定なしなら従来挙動
    merged: Dict[str, str] = {k: v for k, v in file_entries}
    for k, v in ui_entries:
        merged[k] = v  # UI が同一キーで上書き
    return sorted(merged.items(), key=lambda kv: -len(kv[0]))


def reload() -> None:
    """ファイル辞書のキャッシュを破棄(編集後にバックエンド再起動なしで反映する用)。

    UI 辞書は元々キャッシュしないので破棄処理は不要。
    """
    global _cached_file_entries
    with _lock:
        _cached_file_entries = None


def apply(text: str, persona_dict: Optional[Dict[str, str]] = None) -> str:
    """text にユーザー読み方辞書を適用。

    Args:
        text: 入力テキスト(TTS エンジンに渡す直前のもの)
        persona_dict: ペルソナ別オーバーライド辞書。指定された場合、
            global 辞書より**先**に適用される(= persona の方が優先)。

    Returns:
        辞書適用後のテキスト。空入力や辞書不在なら元の text を返す。
    """
    if not text:
        return text

    result = text

    # ペルソナ別 (先に適用 = 後から global で同じキーが上書きされない)
    if persona_dict:
        per_entries = _normalize_entries(persona_dict)
        for key, value in per_entries:
            if key in result:
                result = result.replace(key, value)

    # グローバル
    for key, value in _load_global_entries():
        if key in result:
            result = result.replace(key, value)

    return result
