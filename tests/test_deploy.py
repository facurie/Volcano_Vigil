"""The Space's image and entry point (docs/DEPLOY.md) keep the project's rules: the daily budget, secrets out of git
and the image, the state restored before anything runs, the port the Space card declares, and the dependency
versions the tests pass with."""

import re
import tomllib
from pathlib import Path

from vigil.space import APP_PORT

ROOT = Path(__file__).resolve().parent.parent


def text(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_live_database_is_migrated_before_the_dashboard_starts():
    script = text("deploy", "start.sh")

    assert script.index("db.connect(") < script.index("vigil-web --host")
    assert script.index("vigil-mirror pull") < script.index("db.connect(")


def pyproject():
    return tomllib.loads(text("pyproject.toml"))


def test_the_image_runs_as_an_unprivileged_user_and_copies_no_secrets_or_data():
    dockerfile = text("Dockerfile")

    assert dockerfile.startswith("# ") and "\nFROM python:3.12-slim\n" in dockerfile
    assert "ffmpeg" in dockerfile and "-c deploy/constraints.txt" in dockerfile
    assert "useradd --create-home --uid 1000 vigil" in dockerfile and "\nUSER vigil\n" in dockerfile
    assert not re.search(r"^COPY\s+(\.\s|\S*\.env\b|data\b)", dockerfile, re.MULTILINE)  # no `COPY . .`
    ignored = text(".dockerignore").split()
    assert {".env", ".env.*", "data/"} <= set(ignored)


def test_the_image_carries_the_daily_budget_and_the_dirs_every_service_shares():
    dockerfile = text("Dockerfile")

    assert "DAILY_BUDGET_USD=5" in dockerfile
    assert "ALERT_RESERVE_USD=0.75" in dockerfile
    assert "DATA_DIR=/app/data" in dockerfile and "DB_PATH=/app/data/vigil.sqlite" in dockerfile
    assert "mkdir data && chown vigil:vigil data" in dockerfile


def test_the_dashboard_listens_on_the_port_the_space_card_declares():
    dockerfile, script = text("Dockerfile"), text("deploy", "start.sh")

    assert f"EXPOSE {APP_PORT}\n" in dockerfile
    assert 'CMD ["bash", "deploy/start.sh"]' in dockerfile
    assert f"vigil-web --host 0.0.0.0 --port {APP_PORT} &" in script


def test_the_state_is_restored_before_anything_runs_and_a_failed_restore_stops_the_start():
    script = text("deploy", "start.sh")

    order = ["vigil-persist restore", "vigil-mirror pull", "vigil-web", "vigil-ingest --once",
             "supervise vigil-ingest", "supervise vigil-pipeline", "vigil-persist run"]
    positions = [script.index(step) for step in order]
    assert positions == sorted(positions)
    for line in script.splitlines():
        if line.startswith(("vigil-persist restore", "vigil-mirror pull")):
            assert line.endswith("|| exit 1"), line


def test_the_entry_point_runs_the_existing_clis_with_the_projects_arguments():
    script = text("deploy", "start.sh")

    assert "vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55 || exit 1" in script
    assert "vigil-ingest --once --lookback-hours 24" in script
    assert "supervise vigil-ingest --lookback-hours 24 &" in script
    assert "supervise vigil-pipeline --volcano kilauea &" in script
    assert "supervise vigil-alerts --volcano kilauea &" in script
    assert 'vigil-persist run --bucket "$BUCKET" --interval 300 &' in script
    commands = set(re.findall(r"^(?:supervise )?(vigil-[a-z]+)", script, re.MULTILINE))
    assert commands <= set(pyproject()["project"]["scripts"])


def test_the_state_is_saved_one_last_time_when_the_space_stops():
    script = text("deploy", "start.sh")

    assert "trap stop TERM INT" in script
    assert 'kill "$persist_pid"' in script and 'wait "$persist_pid"' in script


def test_the_services_stop_before_the_last_save_so_nothing_writes_during_it():
    script = text("deploy", "start.sh")

    supervise = script[script.index("supervise() {"):script.index("supervise vigil-ingest")]
    assert 'trap \'kill "$child"' in supervise  # a TERM to the supervisor reaches the service it runs
    stop = script[script.index("stop() {"):]
    order = ['kill "$ingest_pid" "$pipeline_pid" "$alerts_pid"', 'wait "$ingest_pid" "$pipeline_pid" "$alerts_pid"',
             'kill "$persist_pid"', 'wait "$persist_pid"']
    positions = [stop.index(step) for step in order]
    assert positions == sorted(positions)


def test_every_runtime_dependency_is_pinned_for_the_image():
    def name(requirement):
        return re.split(r"[<>=!~\[ ;]", requirement, maxsplit=1)[0].lower().replace("_", "-")

    pins = {}
    for line in text("deploy", "constraints.txt").splitlines():
        if line and not line.startswith("#"):
            package, version = line.split("==")
            pins[name(package)] = version
    for requirement in pyproject()["project"]["dependencies"]:
        assert name(requirement) in pins, requirement
