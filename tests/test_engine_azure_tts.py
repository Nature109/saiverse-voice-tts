"""Tests for AzureTTSEngine.

httpx.stream をモックして:
- SSML 構築 (preset / Personal Voice / style / 言語 / XML エスケープ)
- API key + region 解決の優先順位 (addon UI > config legacy > env)
- voice / personal_voice_id / style の params 解決
- ストリーミング → SynthesisChunk 変換
- 4xx 即例外、5xx は 1 回リトライ
- 奇数バイト chunk 回帰

を検証する。実 API は叩かない。
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from typing import Iterator, List
from unittest.mock import patch

import numpy as np

_PACK_ROOT = Path(__file__).resolve().parent.parent
if str(_PACK_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACK_ROOT))


def _import_engine():
    import importlib
    if "tools.speak.engine.azure_tts" in sys.modules:
        del sys.modules["tools.speak.engine.azure_tts"]
    return importlib.import_module("tools.speak.engine.azure_tts")


def _install_fake_addon_config(get_params_func) -> None:
    pkg = sys.modules.get("saiverse") or types.ModuleType("saiverse")
    sys.modules["saiverse"] = pkg
    fake = types.ModuleType("saiverse.addon_config")
    fake.get_params = get_params_func  # type: ignore[attr-defined]
    sys.modules["saiverse.addon_config"] = fake


def _uninstall_fake_addon_config() -> None:
    sys.modules.pop("saiverse.addon_config", None)


class _FakeStreamResponse:
    def __init__(self, status_code: int, chunks: List[bytes], text: str = ""):
        self.status_code = status_code
        self._chunks = chunks
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request(
                "POST",
                "https://japaneast.tts.speech.microsoft.com/cognitiveservices/v1",
            )
            resp = httpx.Response(self.status_code, request=req, text=self.text)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req, response=resp,
            )

    def iter_bytes(self) -> Iterator[bytes]:
        yield from self._chunks


def _make_pcm_bytes(num_samples: int = 1200, sample_value: int = 100) -> bytes:
    return (np.full(num_samples, sample_value, dtype=np.int16)).tobytes()


class AzureSSMLBuildTests(unittest.TestCase):
    """_build_ssml の検証。"""

    def setUp(self):
        self.mod = _import_engine()
        self.eng = self.mod.AzureTTSEngine({})

    def test_default_preset(self):
        ssml = self.eng._build_ssml(
            "こんにちは", "ja-JP-NanamiNeural", "ja-JP", None, None
        )
        self.assertIn('xml:lang="ja-JP"', ssml)
        self.assertIn('<voice name="ja-JP-NanamiNeural">', ssml)
        self.assertIn("こんにちは", ssml)
        self.assertNotIn("mstts:ttsembedding", ssml)
        self.assertNotIn("mstts:express-as", ssml)

    def test_personal_voice_overrides_voice_to_dragon(self):
        ssml = self.eng._build_ssml(
            "test", "ja-JP-NanamiNeural", "ja-JP", "pvid-123", None
        )
        # Personal Voice 利用時は base voice = DragonLatestNeural に強制
        self.assertIn('<voice name="DragonLatestNeural">', ssml)
        self.assertNotIn('"ja-JP-NanamiNeural"', ssml)
        self.assertIn(
            '<mstts:ttsembedding speakerProfileId="pvid-123">',
            ssml,
        )

    def test_style_wraps_inner(self):
        ssml = self.eng._build_ssml(
            "happy text", "ja-JP-NanamiNeural", "ja-JP", None, "cheerful"
        )
        self.assertIn('<mstts:express-as style="cheerful">', ssml)
        self.assertIn("</mstts:express-as>", ssml)

    def test_xml_escapes_special_chars(self):
        ssml = self.eng._build_ssml(
            'hello & <world>', "ja-JP-NanamiNeural", "ja-JP", None, None
        )
        self.assertIn("hello &amp; &lt;world&gt;", ssml)

    def test_personal_voice_with_style(self):
        ssml = self.eng._build_ssml(
            "x", "ja-JP-NanamiNeural", "ja-JP", "pvid", "calm"
        )
        # 構造: voice DragonLatestNeural > express-as style=calm > ttsembedding > x
        self.assertIn('<voice name="DragonLatestNeural">', ssml)
        self.assertIn('<mstts:express-as style="calm">', ssml)
        self.assertIn('speakerProfileId="pvid"', ssml)


class AzureApiKeyResolutionTests(unittest.TestCase):
    def setUp(self):
        self.mod = _import_engine()

    def tearDown(self):
        _uninstall_fake_addon_config()
        os.environ.pop("AZURE_SPEECH_KEY", None)
        os.environ.pop("AZURE_SPEECH_REGION", None)

    def test_addon_ui_wins(self):
        _install_fake_addon_config(
            lambda addon, persona_id=None: {
                "azure_subscription_key": "ui-key",
                "azure_region": "westus2",
            }
        )
        os.environ["AZURE_SPEECH_KEY"] = "env-key"
        eng = self.mod.AzureTTSEngine(
            {"api_key": "config-key", "region": "config-region"}
        )
        self.assertEqual(eng._resolve_api_key(), "ui-key")
        self.assertEqual(eng._resolve_region(), "westus2")

    def test_config_then_env_fallback(self):
        _install_fake_addon_config(
            lambda addon, persona_id=None: {
                "azure_subscription_key": "",
                "azure_region": "",
            }
        )
        os.environ["AZURE_SPEECH_KEY"] = "env-key"
        os.environ["AZURE_SPEECH_REGION"] = "env-region"
        eng = self.mod.AzureTTSEngine(
            {"api_key": "config-key", "region": "config-region"}
        )
        self.assertEqual(eng._resolve_api_key(), "config-key")
        self.assertEqual(eng._resolve_region(), "config-region")

    def test_env_only(self):
        _install_fake_addon_config(lambda addon, persona_id=None: {})
        os.environ["AZURE_SPEECH_KEY"] = "env-key"
        eng = self.mod.AzureTTSEngine({})
        self.assertEqual(eng._resolve_api_key(), "env-key")

    def test_default_region_japaneast(self):
        _install_fake_addon_config(lambda addon, persona_id=None: {})
        eng = self.mod.AzureTTSEngine({})
        self.assertEqual(eng._resolve_region(), "japaneast")

    def test_no_key_returns_none(self):
        _install_fake_addon_config(lambda addon, persona_id=None: {})
        eng = self.mod.AzureTTSEngine({})
        self.assertIsNone(eng._resolve_api_key())


class AzureParamResolutionTests(unittest.TestCase):
    def setUp(self):
        self.mod = _import_engine()
        self.eng = self.mod.AzureTTSEngine({})

    def test_voice_default(self):
        self.assertEqual(self.eng._resolve_voice(None), "ja-JP-NanamiNeural")

    def test_voice_from_voice_key(self):
        self.assertEqual(
            self.eng._resolve_voice({"voice": "ja-JP-KeitaNeural"}),
            "ja-JP-KeitaNeural",
        )

    def test_voice_from_azure_voice_key(self):
        self.assertEqual(
            self.eng._resolve_voice({"azure_voice": "ja-JP-AoiNeural"}),
            "ja-JP-AoiNeural",
        )

    def test_personal_voice_id_resolved(self):
        self.assertEqual(
            self.eng._resolve_personal_voice_id({"azure_personal_voice_id": "pv-1"}),
            "pv-1",
        )

    def test_personal_voice_id_none(self):
        self.assertIsNone(self.eng._resolve_personal_voice_id({}))

    def test_style_resolved(self):
        self.assertEqual(
            self.eng._resolve_style({"azure_voice_style": "cheerful"}),
            "cheerful",
        )

    def test_style_none(self):
        self.assertIsNone(self.eng._resolve_style({}))

    def test_lang_default(self):
        self.assertEqual(self.eng._resolve_lang({}), "ja-JP")

    def test_lang_override(self):
        self.assertEqual(self.eng._resolve_lang({"lang": "en-US"}), "en-US")


class AzureSynthesizeStreamTests(unittest.TestCase):
    def setUp(self):
        self.mod = _import_engine()
        _install_fake_addon_config(
            lambda addon, persona_id=None: {
                "azure_subscription_key": "test-key",
                "azure_region": "japaneast",
            }
        )

    def tearDown(self):
        _uninstall_fake_addon_config()

    def test_synthesize_aggregates_streamed_chunks(self):
        chunks = [_make_pcm_bytes(1200, 50), _make_pcm_bytes(1200, 100)]
        fake_resp = _FakeStreamResponse(200, chunks)
        eng = self.mod.AzureTTSEngine({})
        with patch("httpx.stream", return_value=fake_resp) as mock_stream:
            result = eng.synthesize("こんにちは")
        # URL に region が入っている
        called_url = mock_stream.call_args.args[1]
        self.assertIn(
            "japaneast.tts.speech.microsoft.com/cognitiveservices/v1",
            called_url,
        )
        # SSML 本文に text と default voice
        sent_body = mock_stream.call_args.kwargs["content"].decode("utf-8")
        self.assertIn("こんにちは", sent_body)
        self.assertIn("ja-JP-NanamiNeural", sent_body)
        # PCM 集約結果
        self.assertEqual(result.sample_rate, 24_000)
        self.assertEqual(result.audio.shape[0], 2400)

    def test_no_api_key_raises(self):
        _install_fake_addon_config(lambda addon, persona_id=None: {})
        os.environ.pop("AZURE_SPEECH_KEY", None)
        eng = self.mod.AzureTTSEngine({})
        with self.assertRaises(RuntimeError) as ctx:
            list(eng.synthesize_stream("hi"))
        self.assertIn("subscription key not configured", str(ctx.exception))

    def test_personal_voice_request_body(self):
        chunks = [_make_pcm_bytes(100)]
        fake_resp = _FakeStreamResponse(200, chunks)
        eng = self.mod.AzureTTSEngine({})
        with patch("httpx.stream", return_value=fake_resp) as mock_stream:
            list(eng.synthesize_stream(
                "test",
                params={"azure_personal_voice_id": "pv-xyz"},
            ))
        sent_body = mock_stream.call_args.kwargs["content"].decode("utf-8")
        self.assertIn("DragonLatestNeural", sent_body)
        self.assertIn('speakerProfileId="pv-xyz"', sent_body)

    def test_4xx_does_not_retry(self):
        fake_resp = _FakeStreamResponse(401, [], text="invalid_key")
        eng = self.mod.AzureTTSEngine({})
        with patch("httpx.stream", return_value=fake_resp) as mock_stream:
            with self.assertRaises(Exception):
                list(eng.synthesize_stream("hi"))
        self.assertEqual(mock_stream.call_count, 1)

    def test_5xx_retries_once(self):
        first = _FakeStreamResponse(503, [], text="busy")
        second = _FakeStreamResponse(200, [_make_pcm_bytes(100)])
        eng = self.mod.AzureTTSEngine({})
        with patch("httpx.stream", side_effect=[first, second]) as mock_stream:
            with patch("time.sleep"):
                list(eng.synthesize_stream("hi"))
        self.assertEqual(mock_stream.call_count, 2)

    def test_odd_byte_chunks_are_handled(self):
        """HTTP chunked transfer で奇数バイトが flush タイミングに重なっても
        例外で死なないこと (OpenAI / ElevenLabs と同じ regression)。"""
        chunks = [
            (np.full(1200, 50, dtype=np.int16)).tobytes() + b"\x00",  # 2401
            (np.full(1200, 60, dtype=np.int16)).tobytes() + b"\x00",  # 2401
            (np.full(1200, 70, dtype=np.int16)).tobytes() + b"\x00",  # 2401
        ]
        fake_resp = _FakeStreamResponse(200, chunks)
        eng = self.mod.AzureTTSEngine({})
        with patch("httpx.stream", return_value=fake_resp):
            received = list(eng.synthesize_stream("hi"))
        self.assertGreaterEqual(len(received), 1)
        total_samples = sum(c.audio.shape[0] for c in received)
        # 7203 byte 中 7202 byte = 3601 samples を numpy 化
        self.assertEqual(total_samples, 3601)


if __name__ == "__main__":
    unittest.main(verbosity=2)
