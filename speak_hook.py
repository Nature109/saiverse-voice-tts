"""Server-side hook handler for the ``persona_speak`` event.

SAIVerse 本体が ``emit_speak`` / ``emit_say`` の末尾でこの関数を呼ぶ。
``addon.json`` の ``server_hooks`` 宣言で本体に登録される。

設計は SAIVerse 本体の ``docs/intent/addon_speak_hooks.md`` を参照。

ハンドラは本体の ``ThreadPoolExecutor`` で隔離実行されるため、ここでは
``enqueue_tts()`` で内部キューに投入してすぐ return する (実合成は voice-tts
パック内の ``_TTSWorker`` スレッドで処理)。
"""
from __future__ import annotations

import logging
from typing import Any

from tools._loaded.speak.playback_worker import enqueue_tts, get_effective_params
from tools._loaded.speak.text_cleaner import clean_text_for_tts

LOGGER = logging.getLogger(__name__)


def on_persona_speak(
    persona_id: str,
    text_for_voice: str,
    message_id: str,
    **_kwargs: Any,
) -> None:
    """ペルソナ発話イベントを TTS キューへ投入する。

    Args:
        persona_id: 発話したペルソナの ID。
        text_for_voice: ``<in_heart>`` 除去済み・spell ブロック処理後のテキスト。
            TTS にはこれを使う。
        message_id: Building history のメッセージ ID。バブル再生ボタンや
            ``audio_ready`` SSE イベントの紐付けキー。
        **_kwargs: ``text_raw`` / ``building_id`` / ``pulse_id`` / ``source`` /
            ``metadata`` 等。本ハンドラでは未使用だが、本体側でペイロード項目が
            増えても壊れないように受ける。
    """
    if not persona_id or not text_for_voice or not message_id:
        return

    # アドオン UI の有効化トグルとペルソナ別 auto_speak フラグを尊重する。
    # アドオン全体が無効なら server_hook 自体が unregister されるため
    # ここに来ないが、念のため _enabled もチェックする。
    params = get_effective_params(persona_id)
    if not params.get("_enabled", True):
        LOGGER.debug(
            "voice-tts speak_hook skipped: addon disabled (persona=%s)",
            persona_id,
        )
        return
    if not params.get("auto_speak", True):
        LOGGER.debug(
            "voice-tts speak_hook skipped: auto_speak=false (persona=%s)",
            persona_id,
        )
        return

    cleaned = clean_text_for_tts(text_for_voice)
    if not cleaned:
        return

    job_id = enqueue_tts(cleaned, persona_id, message_id=message_id)
    LOGGER.debug(
        "voice-tts speak_hook enqueued: persona=%s msg=%s job=%s len=%d",
        persona_id, message_id, job_id, len(cleaned),
    )
