import io
import tarfile
from pathlib import Path

import pytest

from vigil.space import APP_PORT, main, space_readme, stage, deploy

REPO = "facurie/volcano-vigil"
FILES = {"README.md": "# Volcano Vigil\n", "Dockerfile": "FROM python:3.12-slim\n", "vigil/__init__.py": ""}


def archive(files):
    """What `git archive` prints: a tar of the files."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            content = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class FakeApi:
    """Records what `deploy` asks of the Hub, and the files the folder held when it was uploaded."""

    def __init__(self):
        self.created, self.uploads = [], []

    def create_repo(self, repo_id, **kwargs):
        self.created.append((repo_id, kwargs))

    def upload_folder(self, **kwargs):
        folder = Path(kwargs["folder_path"])
        files = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())
        self.uploads.append({**kwargs, "files": files, "readme": (folder / "README.md").read_text(encoding="utf-8")})


def test_the_space_readme_declares_a_docker_space_on_the_apps_port():
    readme = space_readme("# Volcano Vigil\n")

    assert readme.startswith("---\ntitle: Volcano Vigil\n")
    assert "\nsdk: docker\n" in readme and f"\napp_port: {APP_PORT}\n" in readme
    assert readme.endswith("\n---\n\n# Volcano Vigil\n")


def test_stage_unpacks_the_archive_and_puts_the_front_matter_on_the_readme(tmp_path):
    staged = stage(archive(FILES), tmp_path)

    assert staged == ["Dockerfile", "README.md", "vigil/__init__.py"]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == space_readme("# Volcano Vigil\n")
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM python:3.12-slim\n"


def test_stage_refuses_an_archive_that_would_write_outside_its_folder(tmp_path):
    with pytest.raises(tarfile.FilterError):
        stage(archive({"../evil.txt": "x", **FILES}), tmp_path / "out")


def test_deploy_creates_a_protected_docker_space_and_uploads_the_tree():
    api = FakeApi()

    count = deploy(api, REPO, archive(FILES), "abc1234def")

    assert api.created == [(REPO, {"repo_type": "space", "space_sdk": "docker", "visibility": "protected",
                                   "exist_ok": True})]
    [upload] = api.uploads
    assert upload["repo_id"] == REPO and upload["repo_type"] == "space"
    assert upload["delete_patterns"] == ["*"]
    assert upload["commit_message"] == "Deploy abc1234"
    assert upload["files"] == ["Dockerfile", "README.md", "vigil/__init__.py"]
    assert upload["readme"].startswith("---\n")
    assert count == 3


def test_the_cli_deploys_the_committed_tree(monkeypatch, capsys):
    api = FakeApi()
    monkeypatch.setattr("vigil.space.HfApi", lambda: api)
    monkeypatch.setattr("vigil.space.committed_tree", lambda: (archive(FILES), "abc1234def"))

    main(["deploy", "--repo", REPO])

    assert api.uploads[0]["commit_message"] == "Deploy abc1234"
    assert f"https://huggingface.co/spaces/{REPO}" in capsys.readouterr().out
