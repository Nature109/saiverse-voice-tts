"""Tests for tools.speak.pronunciation_dict.

ユーザー読み方辞書(発音上書き)の挙動検証:

- 空入力・辞書不在のフォールバック
- 単一/複数キーの置換
- 長いキー優先(部分一致防止)
- ペルソナ別オーバーライド優先
- 不正な JSON 値の無視
- _ で始まるコメントキーの無視
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Pack root を sys.path に追加
_PACK_ROOT = Path(__file__).resolve().parent.parent
if str(_PACK_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACK_ROOT))


def _import_module():
    """テストごとに pronunciation_dict モジュールをフレッシュにロードする。

    モジュール内のキャッシュ (`_cached_global_entries`) を分離するため。
    """
    import importlib
    if "tools.speak.pronunciation_dict" in sys.modules:
        del sys.modules["tools.speak.pronunciation_dict"]
    return importlib.import_module("tools.speak.pronunciation_dict")


class PronunciationDictApplyTests(unittest.TestCase):
    """apply() 関数の挙動検証(辞書ファイル不在前提)。"""

    def setUp(self):
        # 一時ディレクトリにモック辞書ファイルを置く
        self.tmp_handle = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp_handle.name)
        self.dict_path = self.tmp_dir / "pronunciation_dict.json"
        self.template_path = self.tmp_dir / "pronunciation_dict.json.template"

        # モジュールを差し替えて辞書パスをテスト用に向ける
        self.pd = _import_module()
        self._orig_dict_path = self.pd._DICT_PATH
        self._orig_template_path = self.pd._DICT_TEMPLATE_PATH
        self.pd._DICT_PATH = self.dict_path
        self.pd._DICT_TEMPLATE_PATH = self.template_path
        self.pd.reload()

    def tearDown(self):
        self.pd._DICT_PATH = self._orig_dict_path
        self.pd._DICT_TEMPLATE_PATH = self._orig_template_path
        self.pd.reload()
        self.tmp_handle.cleanup()

    def _write_global_dict(self, data: dict) -> None:
        self.dict_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.pd.reload()

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.pd.apply(""), "")
        self.assertEqual(self.pd.apply(None), None)  # None も passthrough

    def test_no_dict_file_passes_through(self):
        """辞書ファイルが無ければテキストはそのまま返る。"""
        # template も local も存在しない
        self.assertEqual(self.pd.apply("こんにちは、まはー!"), "こんにちは、まはー!")

    def test_single_key_replacement(self):
        self._write_global_dict({"まはー": "マハー"})
        result = self.pd.apply("おはよう、まはー")
        self.assertEqual(result, "おはよう、マハー")

    def test_multiple_keys_replacement(self):
        self._write_global_dict({
            "まはー": "マハー",
            "ナチュレ": "なちゅれ",
        })
        result = self.pd.apply("まはー と ナチュレ")
        self.assertEqual(result, "マハー と なちゅれ")

    def test_longer_key_takes_precedence(self):
        """長いキーが先に適用される(部分一致による誤置換の防止)。

        例: "まはーさん" を "マハーくん" にしたい場合、"まはー" だけの
        エントリより先にマッチするべき。
        """
        self._write_global_dict({
            "まはー": "マハー",
            "まはーさん": "マハーくん",
        })
        result = self.pd.apply("ようこそ、まはーさん")
        # 長いキーが先 → "まはーさん" が "マハーくん" に
        self.assertEqual(result, "ようこそ、マハーくん")

    def test_persona_override_takes_precedence(self):
        """ペルソナ別辞書はグローバルより優先(先に適用される)。"""
        self._write_global_dict({"ナチュレ": "なちゅれ"})
        result = self.pd.apply(
            "ねえ、ナチュレ", persona_dict={"ナチュレ": "なつる"}
        )
        # ペルソナの "なつる" が先に当たり、global は何もしない
        self.assertEqual(result, "ねえ、なつる")

    def test_persona_dict_complements_global(self):
        """ペルソナ辞書に無いキーは global で置換される。"""
        self._write_global_dict({
            "まはー": "マハー",
            "ナチュレ": "なちゅれ",
        })
        result = self.pd.apply(
            "まはー と ナチュレ", persona_dict={"ナチュレ": "なつる"}
        )
        # ペルソナで先にナチュレが置換、global で まはー が置換
        self.assertEqual(result, "マハー と なつる")

    def test_underscore_keys_are_ignored(self):
        """_ で始まるキーはコメント扱いで無視される。"""
        self._write_global_dict({
            "_comment": "this is a comment, not a replacement rule",
            "_example": "ignored",
            "まはー": "マハー",
        })
        result = self.pd.apply("こんにちは、まはー、_comment はどうなる?")
        # まはー だけが置換され、_comment という文字列は触られない
        self.assertEqual(result, "こんにちは、マハー、_comment はどうなる?")

    def test_invalid_json_falls_back_to_passthrough(self):
        """壊れた JSON は例外にせず passthrough。"""
        self.dict_path.write_text("{not valid json", encoding="utf-8")
        self.pd.reload()
        self.assertEqual(self.pd.apply("まはー"), "まはー")

    def test_non_dict_json_is_ignored(self):
        """JSON が dict でない (list/string) 場合は無視。"""
        self.dict_path.write_text("[1, 2, 3]", encoding="utf-8")
        self.pd.reload()
        self.assertEqual(self.pd.apply("まはー"), "まはー")

    def test_non_string_keys_are_skipped(self):
        """キーが str でない値や空文字キーはスキップされる(防御)。"""
        # JSON で非 str キーは作れないが、空文字キーはあり得る
        self._write_global_dict({"": "EMPTY", "まはー": "マハー"})
        result = self.pd.apply("まはー")
        self.assertEqual(result, "マハー")

    def test_no_match_returns_original(self):
        self._write_global_dict({"いない名前": "存在しない"})
        result = self.pd.apply("普通のテキスト")
        self.assertEqual(result, "普通のテキスト")

    def test_template_used_if_local_missing(self):
        """ローカル辞書が無くテンプレートだけある場合、template から自動コピーされる。"""
        self.assertFalse(self.dict_path.exists())
        self.template_path.write_text(
            json.dumps({"まはー": "マハー"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.pd.reload()
        result = self.pd.apply("まはー")
        self.assertEqual(result, "マハー")
        # 副作用: ローカル辞書が template から materialize される
        self.assertTrue(self.dict_path.exists())

    def test_template_does_not_overwrite_local(self):
        """ローカル辞書が既にあれば template はコピーされない(ユーザー編集を保護)。"""
        self._write_global_dict({"X": "Y"})
        self.template_path.write_text(
            json.dumps({"X": "DIFFERENT"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.pd.reload()
        # ローカル版が優先されるので "Y" が返る
        result = self.pd.apply("X")
        self.assertEqual(result, "Y")

    def test_persona_longer_key_precedence(self):
        """ペルソナ辞書内でも長いキーが先に当たる。"""
        result = self.pd.apply(
            "まはーさん",
            persona_dict={
                "まはー": "MAHA",
                "まはーさん": "MAHA-SAN",
            },
        )
        self.assertEqual(result, "MAHA-SAN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
