"""start.sh on Linux with a stub docker: folder choice, preferences and command order."""

import os
import subprocess
from pathlib import Path

import pytest

START = Path("/workspace/start.sh")
STUB = """#!/bin/sh
printf 'ARGS:%s\\n' "$*" >> "$STUB_LOG"
printf 'ARCHIVE:%s\\nIMPORT:%s\\nLABEL:%s\\n' "$HEALTHVIZ_ARCHIVE_DIR" "$HEALTHVIZ_IMPORT_DIR" \
    "$HEALTHVIZ_IMPORT_LABEL" >> "$STUB_LOG"
case "$*" in
  compose*" run "*) exit "${STUB_RUN_STATUS:-0}";;
  compose*" build "*) exit "${STUB_BUILD_STATUS:-0}";;
esac
exit 0
"""


@pytest.fixture
def home(tmp_path):
    (tmp_path / "bin").mkdir()
    docker = tmp_path / "bin/docker"
    docker.write_text(STUB)
    docker.chmod(0o755)
    for name in ("archive", "downloads"):
        (tmp_path / name).mkdir()
    return tmp_path


def start(home, *args, answers="", run_status=0, build_status=0):
    env = {
        "HOME": str(home),
        "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
        "STUB_LOG": str(home / "docker.log"),
        "STUB_RUN_STATUS": str(run_status),
        "STUB_BUILD_STATUS": str(build_status),
    }
    result = subprocess.run(
        ["sh", str(START), *args], input=answers, env=env, capture_output=True, text=True
    )
    log = (home / "docker.log").read_text() if (home / "docker.log").exists() else ""
    (home / "docker.log").unlink(missing_ok=True)
    return result, log


def answers(home, archive="archive", downloads="downloads"):
    return f"{home / archive}\n{home / downloads}\n"


def test_first_run_asks_and_saves_folders(home):
    result, log = start(home, answers=answers(home))

    assert result.returncode == 0, result.stderr
    prefs = (home / ".config/healthviz/launcher.conf").read_text()
    assert prefs == f"archive_dir={home / 'archive'}\nimport_dir={home / 'downloads'}\n"
    assert oct((home / ".config/healthviz/launcher.conf").stat().st_mode & 0o777) == "0o600"
    assert f"ARCHIVE:{home / 'archive'}" in log and f"IMPORT:{home / 'downloads'}" in log
    assert "LABEL:~/downloads" in log
    parent = home / ".cache/open-health-archive"
    assert oct(parent.stat().st_mode & 0o777) == "0o700"
    # The container identity creates the cache so the viewer owns it, as the README does.
    mkdir = next(line for line in log.splitlines() if "os.mkdir" in line)
    assert "--network none" in mkdir and f"src={parent}," in mkdir


def test_saved_folders_are_reused_without_asking(home):
    start(home, answers=answers(home))

    result, log = start(home, answers="")

    assert result.returncode == 0, result.stderr
    assert f"IMPORT:{home / 'downloads'}" in log


def test_choose_asks_again(home):
    start(home, answers=answers(home))
    (home / "other").mkdir()

    result, log = start(home, "--choose", answers=answers(home, downloads="other"))

    assert result.returncode == 0, result.stderr
    assert f"IMPORT:{home / 'other'}" in log
    assert f"import_dir={home / 'other'}" in (home / ".config/healthviz/launcher.conf").read_text()


def test_paths_with_spaces_and_quotes(home):
    odd = home / "my folder" / "it's ü $HOME"
    odd.mkdir(parents=True)

    result, log = start(home, answers=f"{home / 'archive'}\n{odd}\n")

    assert result.returncode == 0, result.stderr
    assert f"IMPORT:{odd}\n" in log
    result, log = start(home, answers="")
    assert f"IMPORT:{odd}\n" in log


def test_missing_folder_stops_before_docker(home):
    result, log = start(home, answers=f"{home / 'nowhere'}\n")

    assert result.returncode == 1
    assert "ARGS:" not in log


def test_import_failure_still_starts_viewer(home):
    result, log = start(home, answers=answers(home), run_status=1)

    assert result.returncode == 0
    assert "Import failed" in result.stderr
    assert "up -d viewer" in log


def test_order_is_stop_import_start(home):
    _, log = start(home, answers=answers(home))

    calls = [line for line in log.splitlines() if line.startswith("ARGS:")]
    words = ("build viewer", "stop viewer", "run --rm", "up -d viewer")
    steps = [next(w for w in words if w in c) for c in calls if "compose" in c]
    # The image is rebuilt every time so an updated checkout is what runs.
    assert steps == ["build viewer", "stop viewer", "run --rm", "up -d viewer"]
    run = next(c for c in calls if "compose" in c and "run --rm" in c)
    assert f"--user {os.getuid()}:{os.getgid()}" in run
    assert run.endswith(" import")


def test_offline_rebuild_failure_keeps_existing_image(home):
    result, log = start(home, answers=answers(home), build_status=1)

    assert result.returncode == 0
    assert "using the existing image" in result.stderr
    assert "up -d viewer" in log


def test_existing_cache_is_left_alone(home):
    cache = home / ".cache/open-health-archive/viewer"
    cache.mkdir(parents=True, mode=0o755)

    _, log = start(home, answers=answers(home))

    assert "os.mkdir" not in log
    assert oct(cache.stat().st_mode & 0o777) == "0o755"


def test_cache_dir_can_be_chosen(home):
    chosen = home / "private cache"
    chosen.mkdir(mode=0o700)

    result, log = start(home, answers=answers(home))
    assert f"src={home / '.cache/open-health-archive'}," in log
    env = {"HEALTHVIZ_CACHE_DIR": str(chosen)}
    result = subprocess.run(
        ["sh", str(START)],
        input="",
        env={
            "HOME": str(home),
            "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
            "STUB_LOG": str(home / "docker.log"),
            **env,
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "os.mkdir" not in (home / "docker.log").read_text()


def test_cache_override_with_any_name_leaves_its_parent_alone(home):
    parent = home / "shared"
    parent.mkdir(mode=0o755)
    env = {
        "HOME": str(home),
        "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
        "STUB_LOG": str(home / "docker.log"),
        "HEALTHVIZ_CACHE_DIR": str(parent / "oha-cache"),
    }

    result = subprocess.run(
        ["sh", str(START)], input=answers(home), env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    mkdir = next(
        line for line in (home / "docker.log").read_text().splitlines() if "os.mkdir" in line
    )
    assert mkdir.endswith(" oha-cache") and f"src={parent}," in mkdir
    assert oct(parent.stat().st_mode & 0o777) == "0o755"
