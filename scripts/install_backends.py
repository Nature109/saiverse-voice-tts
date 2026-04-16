"""Install TTS backend repositories into external/.

Usage:
    python scripts/install_backends.py [qwen3_tts|gpt_sovits|irodori|all]

Clones the upstream repository and downloads required model weights from
HuggingFace. Each backend has its own directory under external/ and is
ignored by this pack's git. All backends use permissive licenses (Apache 2.0
or MIT) and are redistributable.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

LOGGER = logging.getLogger("install_backends")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

_PACK_ROOT = Path(__file__).resolve().parent.parent
_EXTERNAL = _PACK_ROOT / "external"

_REPOS = {
    "qwen3_tts": {
        "url": "https://github.com/QwenLM/Qwen3-TTS.git",
        "dir": "Qwen3-TTS",
        "pip_install": True,
        "hf_weights": ["Qwen/Qwen3-TTS-12Hz-1.7B-Base"],
    },
    "gpt_sovits": {
        "url": "https://github.com/RVC-Boss/GPT-SoVITS.git",
        "dir": "GPT-SoVITS",
        "pip_install": False,
        "hf_weights": ["lj1995/GPT-SoVITS"],
        "weights_local_dir": "GPT-SoVITS/GPT_SoVITS/pretrained_models",
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

    if spec.get("pip_install"):
        _pip_install_editable(repo_dir)

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
        default="qwen3_tts",
    )
    args = parser.parse_args()

    targets = list(_REPOS.keys()) if args.backend == "all" else [args.backend]
    for t in targets:
        install(t)


if __name__ == "__main__":
    main()
