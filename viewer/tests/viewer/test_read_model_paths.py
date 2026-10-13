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
