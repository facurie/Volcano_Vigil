"""Deploy the committed tree as a Hugging Face Docker Space (docs/DEPLOY.md).

    vigil-space deploy --repo facurie/volcano-vigil

`git archive HEAD` sends committed files only, so `.env`, `data/` and the git-excluded briefs never leave this
machine. The Space is created "protected": its code is private and its app is public. Every deploy makes the Hub
rebuild the image and restart the Space; the live state comes back from its bucket (vigil/persist.py).
"""

from __future__ import annotations

import argparse
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

APP_PORT = 7860  # the port vigil-web listens on (deploy/start.sh) and the Hub proxies to

CARD = f"""---
title: Volcano Vigil
emoji: 🌋
colorFrom: red
colorTo: gray
sdk: docker
app_port: {APP_PORT}
pinned: false
short_description: Kīlauea webcams to measurements and ES/EN bulletins
---

"""


def space_readme(readme: str) -> str:
    """The repository's README with the Space's configuration on top, where the Hub reads it."""
    return CARD + readme


def stage(archive: bytes, out: Path) -> list[str]:
    """Unpack a tar of the repository into `out` (refusing any member that would land outside it) and put the
    Space's front matter on its README. Returns the staged paths, sorted."""
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(out, filter="data")
    readme = out / "README.md"
    readme.write_text(space_readme(readme.read_text(encoding="utf-8")), encoding="utf-8")
    return sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())


def deploy(api: HfApi, repo_id: str, archive: bytes, revision: str) -> int:
    """Create the Space if needed and upload the tree in `archive`, deleting what the tree no longer has. Returns
    how many files were uploaded."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(archive, Path(tmp))
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", visibility="protected", exist_ok=True)
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp,
                          commit_message=f"Deploy {revision[:7]}", delete_patterns=["*"])
    return len(staged)


def committed_tree() -> tuple[bytes, str]:
    """`git archive HEAD` as tar bytes, and the commit it archives."""
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], capture_output=True, check=True).stdout
    return archive, revision


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deploy the committed tree (HEAD) as a Hugging Face Docker Space.")
    parser.add_argument("action", choices=["deploy"])
    parser.add_argument("--repo", required=True, help="Space id, e.g. facurie/volcano-vigil")
    args = parser.parse_args(argv)

    archive, revision = committed_tree()
    count = deploy(HfApi(), args.repo, archive, revision)
    print(f"{count} files of {revision[:7]} deployed to https://huggingface.co/spaces/{args.repo}")


if __name__ == "__main__":
    main()
