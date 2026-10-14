import json
import math
import os
import tempfile
import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from healthviz.archive.schema import TABLES


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    archive_dir: str | None = None
    birth_year: int | None = None
    max_hr: float | None = None
    worn_hours_threshold: int = 10
    default_timezone: str = "UTC"
    priority: dict[str, list[str]] = field(default_factory=dict)
    ingest_priority: dict[str, list[str]] = field(default_factory=dict)
    device_aliases: dict[str, str] = field(default_factory=dict)
    # Dashboard app filter by readable label; empty means every app.
    apps: list[str] = field(default_factory=list)

    def validate(self) -> None:
        try:
            if self.archive_dir is not None and (
                not isinstance(self.archive_dir, str) or not self.archive_dir
            ):
                raise ValueError
            if (
                type(self.worn_hours_threshold) is not int
                or not 1 <= self.worn_hours_threshold <= 25
            ):
                raise ValueError
            if self.birth_year is not None and (
                type(self.birth_year) is not int or not 1900 <= self.birth_year <= date.today().year
            ):
                raise ValueError
            if self.max_hr is not None and (
                type(self.max_hr) not in (int, float)
                or not math.isfinite(self.max_hr)
                or self.max_hr <= 0
            ):
                raise ValueError
            ZoneInfo(self.default_timezone)
            for mapping in (self.priority, self.ingest_priority):
                if not isinstance(mapping, dict):
                    raise ValueError
                for key, values in mapping.items():
                    if (
                        not isinstance(key, str)
                        or not key
                        or not isinstance(values, list)
                        or any(not isinstance(v, str) or not v for v in values)
                        or len(set(values)) != len(values)
                    ):
                        raise ValueError
            if set(self.priority) - (
                set(TABLES) - {"devices", "sleep_stages"}
                | {"active_kcal", "total_kcal", "sleep_duration"}
            ):
                raise ValueError
            if not isinstance(self.device_aliases, dict) or any(
                not isinstance(k, str)
                or not k
                or not isinstance(v, str)
                or not v
                or v in self.device_aliases
                for k, v in self.device_aliases.items()
            ):
                raise ValueError
            if (
                not isinstance(self.apps, list)
                or any(not isinstance(a, str) or not a for a in self.apps)
                or len(set(self.apps)) != len(self.apps)
            ):
                raise ValueError
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            raise SettingsError(
                "config: invalid profile, threshold, timezone or source priority"
            ) from None

    def check_devices(self, ids: set[str]) -> None:
        self.validate()
        references = (
            set(self.device_aliases) | set(self.device_aliases.values()) | set(self.ingest_priority)
        )
        references.update(v for values in self.priority.values() for v in values)
        if not references.issubset(ids):
            raise SettingsError("config: source settings reference an unknown device")


def load_settings(path: Path) -> Settings:
    try:
        if not path.exists():
            return Settings()
        data = tomllib.loads(path.read_text())
        profile = data.pop("profile", {})
        if (
            not isinstance(profile, dict)
            or set(profile) - {"birth_year", "max_hr"}
            or set(data)
            - {f.name for f in fields(Settings) if f.name not in ("birth_year", "max_hr")}
        ):
            raise ValueError
        value = Settings(**data, **profile)
        value.validate()
        return value
    except (OSError, ValueError, TypeError):
        raise SettingsError("config: cannot read valid settings") from None


def save_settings(path: Path, settings: Settings) -> None:
    settings.validate()

    def quote(value):
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f"worn_hours_threshold = {settings.worn_hours_threshold}",
        f"default_timezone = {quote(settings.default_timezone)}",
    ]
    if settings.archive_dir is not None:
        lines.append(f"archive_dir = {quote(settings.archive_dir)}")
    if settings.apps:
        lines.append(f"apps = {quote(settings.apps)}")
    lines.append("\n[profile]")
    for key in ("birth_year", "max_hr"):
        value = getattr(settings, key)
        if value is not None:
            lines.append(f"{key} = {value}")
    for key in ("priority", "ingest_priority", "device_aliases"):
        lines.append(f"\n[{key}]")
        lines.extend(f"{quote(k)} = {quote(v)}" for k, v in sorted(getattr(settings, key).items()))
    name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
        with os.fdopen(fd, "w") as out:
            out.write("\n".join(lines) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    except OSError:
        raise SettingsError("config: cannot save settings") from None
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
