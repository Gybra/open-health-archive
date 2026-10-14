import importlib
import math
from dataclasses import replace

import pytest


def settings():
    assert importlib.util.find_spec("healthviz.settings"), "private settings are missing"
    return importlib.import_module("healthviz.settings")


def test_settings_roundtrip_and_validation(tmp_path):
    mod = settings()
    path = tmp_path / "config.toml"
    default = mod.load_settings(path)
    assert default.worn_hours_threshold == 10
    value = replace(
        default,
        archive_dir='/fictional/quote"folder',
        birth_year=1986,
        max_hr=190,
        priority={"steps": ["watch-a"]},
        ingest_priority={"watch-a": ["xiaomi_export", "health_connect"]},
        device_aliases={"watch-b": "watch-a"},
    )
    mod.save_settings(path, value)
    assert mod.load_settings(path) == value
    assert path.stat().st_mode & 0o777 == 0o600
    old = path.read_bytes()
    for changes in [
        {"max_hr": math.inf},
        {"max_hr": 0},
        {"birth_year": 1899},
        {"birth_year": 9999},
        {"worn_hours_threshold": 0},
        {"worn_hours_threshold": 26},
        {"default_timezone": "PRIVATE-SENTINEL"},
        {"priority": {"bad_metric": ["x"]}},
        {"priority": {"steps": ["x", "x"]}},
        {"device_aliases": {"a": "b", "b": "a"}},
    ]:
        with pytest.raises(mod.SettingsError) as error:
            mod.save_settings(path, replace(default, **changes))
        assert "PRIVATE-SENTINEL" not in str(error.value)
        assert path.read_bytes() == old
    path.write_text('max_hr = "PRIVATE-SENTINEL"')
    with pytest.raises(mod.SettingsError) as error:
        mod.load_settings(path)
    assert "PRIVATE-SENTINEL" not in str(error.value)


def test_not_same_devices_round_trip_and_validation(tmp_path):
    mod = settings()
    path = tmp_path / "config.toml"
    value = mod.Settings(not_same_devices=[["a", "b"], ["b", "c"]])
    mod.save_settings(path, value)
    assert mod.load_settings(path) == value
    with pytest.raises(mod.SettingsError):
        value.check_devices({"a", "b"})
    for pairs in [[["b", "a"]], [["a", "a"]], [["a"]], [["a", "b"], ["a", "b"]], [["a", ""]]]:
        with pytest.raises(mod.SettingsError):
            mod.Settings(not_same_devices=pairs).validate()
