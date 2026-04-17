"""Install TTS backend repositories into external/.

Usage:
    python scripts/install_backends.py [gpt_sovits|irodori|all]

Clones the upstream repository and downloads required model weights from
HuggingFace. Each backend has its own directory under external/ and is
ignored by this pack's git. All backends use permissive licenses (Apache 2.0
or MIT) and are redistributable.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

LOGGER = logging.getLogger("install_backends")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Windows + MSVC で C/C++ 拡張をソースビルドする際、CP932 (Shift-JIS) ロケールの
# 環境だと非 ASCII 文字を含むソースファイルで字句解析が狂いコンパイルエラーになる
# ケースがある (editdistance, opencc 等)。/utf-8 フラグを MSVC に渡しておくことで
# Python 3.13+ など wheel が未提供のバージョンでもソースビルドが通るようにする。
if sys.platform == "win32":
    os.environ.setdefault("CL", "/utf-8")

_PACK_ROOT = Path(__file__).resolve().parent.parent
_EXTERNAL = _PACK_ROOT / "external"

_REPOS = {
    "gpt_sovits": {
        "url": "https://github.com/RVC-Boss/GPT-SoVITS.git",
        "dir": "GPT-SoVITS",
        "pip_install": False,
        "pip_install_requirements": "requirements.txt",
        "pre_install_pip": ["opencc-python-reimplemented"],
        "strip_opencc_from_requirements": True,
        "extra_dirs": ["GPT_SoVITS/pretrained_models/fast_langdetect"],
        "hf_weights": ["lj1995/GPT-SoVITS"],
        "weights_local_dir": "external/GPT-SoVITS/GPT_SoVITS/pretrained_models",
    },
    "irodori": {
        "url": "https://github.com/Aratako/Irodori-TTS.git",
        "dir": "Irodori-TTS",
        "pip_install": True,
        "hf_weights": [
            "Aratako/Irodori-TTS-500M-v2",
            "Aratako/Semantic-DACVAE-Japanese-32dim",
        ],
    },
}


def _strip_opencc_from_requirements(req_path: Path) -> None:
    """Comment out `opencc` and drop `--no-binary=opencc` from requirements.txt.

    Upstream ``opencc`` fails to build on Windows without a specific C++
    toolchain (Access Denied during build). We replace it with the pure-Python
    ``opencc-python-reimplemented`` (installed via pre_install_pip) which
    exposes the same API GPT-SoVITS depends on.
    """
    if not req_path.exists():
        return
    original = req_path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    changed = False
    for line in original.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("--no-binary=opencc"):
            changed = True
            continue
        if (
            stripped == "opencc"
            or stripped.startswith("opencc==")
            or stripped.startswith("opencc>=")
            or stripped.startswith("opencc<")
            or stripped.startswith("opencc~")
        ):
            out_lines.append(f"# {line}  # stripped by install_backends.py")
            changed = True
            continue
        out_lines.append(line)
    if changed:
        req_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        LOGGER.info("Stripped opencc from %s", req_path)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    LOGGER.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _clone(url: str, dest: Path) -> None:
    if dest.exists():
        LOGGER.info("Already cloned: %s", dest)
        return
    _run(["git", "clone", "--depth", "1", url, str(dest)])


def _pip_install_editable(repo_dir: Path) -> None:
    _run([sys.executable, "-m", "pip", "install", "-e", str(repo_dir)])


def _hf_snapshot_download(repo_id: str, local_dir: Path | None = None) -> None:
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError:
        _run([sys.executable, "-m", "pip", "install", "huggingface_hub"])
        from huggingface_hub import snapshot_download  # type: ignore

    LOGGER.info("Downloading HF weights: %s", repo_id)
    kwargs = {"repo_id": repo_id}
    if local_dir:
        kwargs["local_dir"] = str(local_dir)
    snapshot_download(**kwargs)


def install(backend: str) -> None:
    if backend not in _REPOS:
        raise ValueError(f"Unknown backend: {backend}")

    spec = _REPOS[backend]
    _EXTERNAL.mkdir(parents=True, exist_ok=True)
    repo_dir = _EXTERNAL / spec["dir"]

    _clone(spec["url"], repo_dir)

    for pkg in spec.get("pre_install_pip", []):
        _run([sys.executable, "-m", "pip", "install", pkg])

    if spec.get("pip_install"):
        _pip_install_editable(repo_dir)

    req_file = spec.get("pip_install_requirements")
    if req_file:
        req_path = repo_dir / req_file
        if req_path.exists():
            if spec.get("strip_opencc_from_requirements"):
                _strip_opencc_from_requirements(req_path)
            _run([sys.executable, "-m", "pip", "install", "-r", str(req_path)])
        else:
            LOGGER.warning("requirements file not found: %s", req_path)

    for sub in spec.get("extra_dirs", []):
        target = repo_dir / sub
        target.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Ensured directory exists: %s", target)

    weights_local = None
    if "weights_local_dir" in spec:
        weights_local = _PACK_ROOT / spec["weights_local_dir"]
        weights_local.mkdir(parents=True, exist_ok=True)

    for hf_repo in spec.get("hf_weights", []):
        _hf_snapshot_download(hf_repo, local_dir=weights_local)

    LOGGER.info("Backend installed: %s", backend)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install TTS backends for saiverse-voice-tts.")
    parser.add_argument(
        "backend",
        choices=list(_REPOS.keys()) + ["all"],
        nargs="?",
        default="gpt_sovits",
    )
    args = parser.parse_args()

    targets = list(_REPOS.keys()) if args.backend == "all" else [args.backend]
    for t in targets:
        install(t)


if __name__ == "__main__":
    main()
