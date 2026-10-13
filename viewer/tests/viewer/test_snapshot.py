import json
import os

import pytest
from viewer_archive import write_viewer_archive

from healthviz.archive import reader


@pytest.mark.parametrize(
    "relative,before,after",
    [
        ("heart_rate/2026-01.csv", b",60,", b",61,"),
        ("tracks/walk.gpx", b"0.003", b"0.004"),
    ],
)
def test_content_verification_rejects_restored_mtime(tmp_path, relative, before, after):
    assert hasattr(reader, "verify_snapshot"), "verified content identity is missing"
    root = write_viewer_archive(tmp_path)
    token, digest = reader.verify_snapshot(root)
    assert token == reader.archive_token(root)
    assert len(digest) == 64
    path = root / relative
    stat = path.stat()
    data = path.read_bytes()
    assert before in data
    path.write_bytes(data.replace(before, after))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert reader.archive_token(root) == token
    with pytest.raises(reader.ArchiveReadError):
        reader.verify_snapshot(root)


def test_verification_ignores_access_time(tmp_path):
    root = write_viewer_archive(tmp_path)
    path = root / "heart_rate/2026-01.csv"
    stat = path.stat()
    os.utime(path, ns=(0, stat.st_mtime_ns))
    assert len(reader.verify_snapshot(root)[1]) == 64


@pytest.mark.parametrize("change", ["schema", "missing", "extra", "symlink", "manifest"])
def test_invalid_snapshot_is_rejected(tmp_path, change):
    root = write_viewer_archive(tmp_path / "archive")
    manifest = root / "manifest.json"
    if change == "schema":
        data = json.loads(manifest.read_bytes())
        data["schema_version"] = 99
        manifest.write_text(json.dumps(data))
    elif change == "missing":
        (root / "heart_rate/2026-01.csv").unlink()
    elif change == "extra":
        (root / "extra.csv").write_text("PRIVATE-SENTINEL")
    elif change == "symlink":
        (root / "link").symlink_to(tmp_path, target_is_directory=True)
    else:
        manifest.write_text("PRIVATE-SENTINEL")
    with pytest.raises(reader.ArchiveReadError) as error:
        reader.verify_snapshot(root)
    assert "PRIVATE-SENTINEL" not in str(error.value)


def test_manifest_swap_during_hashing_rejects_snapshot(tmp_path, monkeypatch):
    root = write_viewer_archive(tmp_path)
    check = reader.check_manifest

    def mutate(*args):
        result = check(*args)
        path = root / "manifest.json"
        data = path.read_bytes()
        stat = path.stat()
        path.write_bytes(data + b" ")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return result

    monkeypatch.setattr(reader, "check_manifest", mutate)
    with pytest.raises(reader.ArchiveReadError):
        reader.verify_snapshot(root)
