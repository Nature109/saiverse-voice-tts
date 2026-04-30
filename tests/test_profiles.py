"""Tests for tools.speak.profiles.

profile 解決の各層 (UI / registry / fallback) と、UI 設定の pronunciation_dict が
registry ルート時にもマージされる挙動を検証する。
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

# Pack root を sys.path に追加
_PACK_ROOT = Path(__file__).resolve().parent.parent
if str(_PACK_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACK_ROOT))


def _install_fake_addon_config(get_params_func) -> None:
    """`saiverse.addon_config.get_params` をテスト用関数に差し替える。"""
    pkg = sys.modules.get("saiverse") or types.ModuleType("saiverse")
    sys.modules["saiverse"] = pkg
    fake = types.ModuleType("saiverse.addon_config")
    fake.get_params = get_params_func  # type: ignore[attr-defined]
    sys.modules["saiverse.addon_config"] = fake


def _uninstall_fake_addon_config() -> None:
    sys.modules.pop("saiverse.addon_config", None)


def _import_profiles():
    """profiles モジュールをフレッシュにロードする (キャッシュ分離用)。"""
    import importlib
    if "tools.speak.profiles" in sys.modules:
        del sys.modules["tools.speak.profiles"]
    return importlib.import_module("tools.speak.profiles")


class GetProfileTests(unittest.TestCase):
    """get_profile() の挙動検証。registry.json の中身を一時ファイルで差し替える。"""

    def setUp(self):
        self.tmp_handle = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp_handle.name)
        self.registry_path = self.tmp_dir / "registry.json"
        self.template_path = self.tmp_dir / "registry.json.template"

        self.pf = _import_profiles()
        self._orig_registry = self.pf._REGISTRY_PATH
        self._orig_template = self.pf._REGISTRY_TEMPLATE_PATH
        self.pf._REGISTRY_PATH = self.registry_path
        self.pf._REGISTRY_TEMPLATE_PATH = self.template_path
        self.pf.reload_registry()

    def tearDown(self):
        self.pf._REGISTRY_PATH = self._orig_registry
        self.pf._REGISTRY_TEMPLATE_PATH = self._orig_template
        self.pf.reload_registry()
        _uninstall_fake_addon_config()
        self.tmp_handle.cleanup()

    def _write_registry(self, data: dict) -> None:
        self.registry_path.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        self.pf.reload_registry()

    # --- _try_get_ui_pronunciation_dict ---

    def test_ui_pd_returns_dict_when_set(self):
        def fake_get_params(addon, persona_id=None):
            return {"pronunciation_dict": {"まはー": "マハー"}}
        _install_fake_addon_config(fake_get_params)

        result = self.pf._try_get_ui_pronunciation_dict("Yui_city_a")
        self.assertEqual(result, {"まはー": "マハー"})

    def test_ui_pd_returns_none_when_empty(self):
        def fake_get_params(addon, persona_id=None):
            return {"pronunciation_dict": {}}
        _install_fake_addon_config(fake_get_params)

        result = self.pf._try_get_ui_pronunciation_dict("Yui_city_a")
        self.assertIsNone(result)

    def test_ui_pd_returns_none_when_missing(self):
        def fake_get_params(addon, persona_id=None):
            return {}
        _install_fake_addon_config(fake_get_params)

        result = self.pf._try_get_ui_pronunciation_dict("Yui_city_a")
        self.assertIsNone(result)

    def test_ui_pd_returns_none_when_persona_id_none(self):
        # addon_config 呼ばずに即 None を返す
        def fake_get_params(addon, persona_id=None):  # pragma: no cover (呼ばれない想定)
            raise AssertionError("should not be called")
        _install_fake_addon_config(fake_get_params)

        self.assertIsNone(self.pf._try_get_ui_pronunciation_dict(None))

    def test_ui_pd_returns_none_when_addon_config_unavailable(self):
        # saiverse.addon_config が無い環境を再現
        _uninstall_fake_addon_config()
        self.assertIsNone(self.pf._try_get_ui_pronunciation_dict("Yui_city_a"))

    # --- get_profile: registry root + UI pronunciation_dict merge ---

    def test_registry_entry_with_ui_pd_merge(self):
        """registry に persona エントリがあり、UI に pronunciation_dict が
        セットされている場合、最終 profile にマージされる。"""
        self._write_registry({
            "Yui_city_a": {
                "engine": "gpt_sovits",
                "ref_audio": "samples/Yui_city_a/ref.wav",
                "ref_text": "結衣ペルソナの参照音声",
            },
        })

        def fake_get_params(addon, persona_id=None):
            # _try_addon_persona_config 呼び出し時は ref_audio 無し → None 路線へ
            # _try_get_ui_pronunciation_dict 呼び出し時に dict を返す
            return {"pronunciation_dict": {"まはー": "マハー"}}
        _install_fake_addon_config(fake_get_params)

        profile = self.pf.get_profile("Yui_city_a")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["engine"], "gpt_sovits")  # registry 由来
        self.assertEqual(profile["pronunciation_dict"], {"まはー": "マハー"})

    def test_registry_entry_ui_pd_overrides_registry_pd(self):
        """registry に pronunciation_dict、UI にも pronunciation_dict がある場合、
        UI 側で上書きされる。"""
        self._write_registry({
            "Yui_city_a": {
                "engine": "gpt_sovits",
                "ref_audio": "samples/Yui_city_a/ref.wav",
                "ref_text": "x",
                "pronunciation_dict": {"古い": "FROM_REGISTRY"},
            },
        })

        def fake_get_params(addon, persona_id=None):
            return {"pronunciation_dict": {"新しい": "FROM_UI"}}
        _install_fake_addon_config(fake_get_params)

        profile = self.pf.get_profile("Yui_city_a")
        self.assertEqual(profile["pronunciation_dict"], {"新しい": "FROM_UI"})

    def test_registry_pd_kept_when_ui_pd_empty(self):
        """UI の pronunciation_dict が空なら registry 側の辞書がそのまま残る。"""
        self._write_registry({
            "Yui_city_a": {
                "engine": "gpt_sovits",
                "ref_audio": "samples/Yui_city_a/ref.wav",
                "ref_text": "x",
                "pronunciation_dict": {"古い": "FROM_REGISTRY"},
            },
        })

        def fake_get_params(addon, persona_id=None):
            return {"pronunciation_dict": {}}
        _install_fake_addon_config(fake_get_params)

        profile = self.pf.get_profile("Yui_city_a")
        self.assertEqual(profile["pronunciation_dict"], {"古い": "FROM_REGISTRY"})

    def test_default_fallback_with_ui_pd(self):
        """registry に persona エントリは無いが _default はあり、UI に pronunciation_dict が
        ある場合、_default ベース + UI 辞書 マージ。"""
        self._write_registry({
            "_default": {
                "engine": "gpt_sovits",
                "ref_audio": "samples/_default/ref.wav",
                "ref_text": "default",
            },
        })

        def fake_get_params(addon, persona_id=None):
            return {"pronunciation_dict": {"まはー": "マハー"}}
        _install_fake_addon_config(fake_get_params)

        profile = self.pf.get_profile("UnknownPersona")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["pronunciation_dict"], {"まはー": "マハー"})

    def test_no_registry_no_addon_returns_none(self):
        """registry も _default も空、UI も空 → None。"""
        self._write_registry({})

        def fake_get_params(addon, persona_id=None):
            return {}
        _install_fake_addon_config(fake_get_params)

        profile = self.pf.get_profile("Yui_city_a")
        self.assertIsNone(profile)

    def test_addon_full_profile_takes_precedence(self):
        """UI で ref_audio まで設定されていれば、addon_config がフルプロファイルとして優先される。"""
        self._write_registry({
            "Yui_city_a": {
                "engine": "gpt_sovits",
                "ref_audio": "samples/Yui_city_a/ref.wav",
                "ref_text": "from registry",
            },
        })

        def fake_get_params(addon, persona_id=None):
            # _try_addon_persona_config 経路: ref_audio あり → フルプロファイルが返る
            return {
                "ref_audio": "/abs/path/to/ui_ref.wav",
                "ref_text": "from UI",
                "engine": "irodori",
                "pronunciation_dict": {"UI": "Persona"},
            }
        _install_fake_addon_config(fake_get_params)

        profile = self.pf.get_profile("Yui_city_a")
        self.assertEqual(profile["engine"], "irodori")
        self.assertEqual(profile["ref_text"], "from UI")
        self.assertEqual(profile["pronunciation_dict"], {"UI": "Persona"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
