import subprocess
import sys
from pathlib import Path

from healthviz.settings import SettingsError, load_settings


def view(
    archive: Path | None,
    *,
    config: Path,
    offline: bool = False,
    lan: bool = False,
    container: bool = False,
    cache_dir: Path | None = None,
) -> int:
    try:
        settings = load_settings(config)
        root = archive or (Path(settings.archive_dir) if settings.archive_dir else None)
        if root and config.resolve().is_relative_to(root.resolve()):
            raise SettingsError("config: choose a directory outside the archive")
        app = Path(__file__).parent / "dashboard/app.py"
        argv = [
            sys.executable,
            "-m",
            "healthviz.server",
            "run",
            str(app),
            f"--server.address={'0.0.0.0' if container or lan else '127.0.0.1'}",
            "--server.port=8501",
            "--browser.gatherUsageStats=false",
            "--browser.serverAddress=127.0.0.1",
            "--client.showErrorDetails=none",
            "--client.toolbarMode=minimal",
            "--server.fileWatcherType=none",
            "--server.headless=true",
            "--server.enableStaticServing=true",
            "--",
            "--config",
            str(config),
        ]
        if root:
            argv.extend(["--archive", str(root)])
        if cache_dir is not None:
            argv.extend(["--cache-dir", str(cache_dir)])
        if offline:
            argv.append("--offline")
        return subprocess.run(argv, check=False).returncode
    except (OSError, SettingsError):
        print("viewer failed: check the archive and private config location", file=sys.stderr)
        return 1
