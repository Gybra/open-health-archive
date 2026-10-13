import hashlib
from dataclasses import dataclass

from healthviz.archive.schema import Row
from healthviz.xiaomi.source import XiaomiExport

INGEST = "xiaomi_export"
SOURCE_APP = "com.mi.health"


@dataclass(frozen=True)
class Device:
    device_id: str
    vendor: str
    model: str
    kind: str


UNKNOWN_DEVICE = Device("xiaomi-unknown", "", "", "other")


def source_device_id(source_id: str, kind: str) -> str:
    # Source-local pseudonym, not an account ID; names can change or collide.
    fingerprint = hashlib.sha256(source_id.encode()).hexdigest()[:16]
    return f"xiaomi-{kind}-{fingerprint}"


def load_devices(export: XiaomiExport) -> dict[str, Device]:
    result = {}
    for _, row in export.rows("data_source"):
        model, name = row["Model"], row["Name"].strip()
        kind = "other"
        if model.startswith("midr.watch."):
            kind = "watch"
        for suffix, label in ((".phone", "phone"), (".manually", "manual"), (".app", "app")):
            if model.endswith(suffix):
                kind = label
        identifier = source_device_id(row["Sid"], kind)
        result[row["Sid"]] = Device(identifier, "Xiaomi" if kind == "watch" else "", name, kind)
    return result


def device_for(export: XiaomiExport, devices, source: Row, table: str) -> Device:
    device = devices.get(source.get("Sid"))
    if device is None:
        export.warn_once(table, "rows from an unknown device")
        return Device(source_device_id(source.get("Sid", ""), "other"), "", "", "other")
    return device


def provenance(device: Device, record_id: str) -> Row:
    return dict(
        device_id=device.device_id, ingest=INGEST, source_app=SOURCE_APP, record_id=record_id
    )
