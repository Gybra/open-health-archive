import json
import os

import pytest
from test_read_model import module, prepare

from healthviz.settings import Settings


@pytest.mark.parametrize(
    "unsafe", ["mode", "link", "archive", "config", "ancestor", "lock", "pointer"]
)
def test_unsafe_cache_is_refused_without_population(tmp_path, unsafe):
    mod = module()
    root, cache, config = prepare(tmp_path)
    if unsafe == "mode":
        cache.chmod(0o755)
    elif unsafe == "link":
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        cache.rmdir()
        cache.symlink_to(target, target_is_directory=True)
    elif unsafe == "archive":
        cache = root / "cache"
        cache.mkdir(mode=0o700)
    elif unsafe == "config":
        cache = config.parent
        cache.mkdir(mode=0o700)
    elif unsafe == "ancestor":
        cache = tmp_path
    elif unsafe == "lock":
        (cache / ".lock").write_text("PRIVATE-SENTINEL")
        (cache / ".lock").chmod(0o644)
    else:
        (cache / "current.json").symlink_to(config)
    with pytest.raises(mod.ReadModelError) as error:
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert "PRIVATE-SENTINEL" not in str(error.value)
    assert not list(cache.glob("*.duckdb"))


def test_private_files_and_pointer_traversal(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    for path in cache.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_uid == os.geteuid()
    pointer = cache / "current.json"
    pointer.write_text(json.dumps({"file": "../outside.duckdb", "sha256": "0" * 64}))
    original = mod.file_checksum

    def confined(path):
        assert path.parent == cache and ".." not in path.parts, "cache path escaped"
        return original(path)

    monkeypatch.setattr(mod, "file_checksum", confined)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert ".." not in json.loads(pointer.read_bytes())["file"]


def test_native_spill_default_stays_inside_private_cache(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    candidate = cache / (".building-generation-" + "0" * 32 + ".duckdb")
    with mod.store.connection(candidate, read_only=False) as conn:
        assert (
            conn.execute("SELECT current_setting('temp_directory')").fetchone()[0]
            == str(candidate) + ".tmp"
        )
        assert (
            conn.execute("SELECT current_setting('enable_external_access')").fetchone()[0] is False
        )


def test_unrecognized_spill_contents_do_not_block_rebuilds(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    old = json.loads((cache / "current.json").read_bytes())["file"]
    spill = cache / (".building-generation-" + "1" * 32 + ".duckdb.tmp")
    spill.mkdir(mode=0o700)
    unknown = spill / "duckdb_temp_block-7.block"
    unknown.write_bytes(b"synthetic spill")
    version = mod.store.FORMAT_VERSION
    for step in (1, 2):
        # A new storage format makes a new generation; settings changes would keep this one.
        monkeypatch.setattr(mod.store, "FORMAT_VERSION", version + step)
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert unknown.read_bytes() == b"synthetic spill"
    assert not (cache / old).exists()
    assert len(list(cache.glob("generation-*.duckdb"))) == 1


def test_shared_spill_directory_is_refused(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    filename = json.loads((cache / "current.json").read_bytes())["file"]
    spill = cache / (filename + ".tmp")
    spill.mkdir()
    spill.chmod(0o755)
    with pytest.raises(mod.ReadModelError):
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)


def test_obsolete_private_spill_directory_is_cleaned(tmp_path):
    from dataclasses import replace

    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    filename = json.loads((cache / "current.json").read_bytes())["file"]
    spill = cache / (filename + ".tmp")
    spill.mkdir(mode=0o700)
    part = spill / "duckdb_temp_storage_S0-0.tmp"
    part.write_bytes(b"synthetic spill")
    part.chmod(0o600)
    unfamiliar = cache / "keep-this-file"
    unfamiliar.write_bytes(b"unrelated")
    mod.load_read_model(
        root, replace(Settings(), worn_hours_threshold=11), cache_dir=cache, config=config
    )
    assert not spill.exists()
    assert unfamiliar.read_bytes() == b"unrelated"
