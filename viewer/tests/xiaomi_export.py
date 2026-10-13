import csv
import json

WATCH_SID = "900"
MANUAL_SID = "901"
HEADERS = {
    "data_source": "Uid Sid Identifier Model Name Alias Status CreateTime UpdateTime",
    "fitness_data": "Uid Sid Key Time Value UpdateTime",
    "aggregated_fitness_data": "Uid Sid Tag Key Time Value UpdateTime",
    "sport_record": "Uid Sid Key Time Category Value UpdateTime",
    "sport_track_data": "Uid Did Key Time UpdateTime GPX",
}


def fitness_row(key, time, value, sid=WATCH_SID):
    return dict(
        Uid="1", Sid=sid, Key=key, Time=str(time), Value=json.dumps(value), UpdateTime=str(time)
    )


def sport_row(key, time, value, sid=WATCH_SID):
    return {**fitness_row(key, time, value, sid), "Category": key}


def track_row(time, url, key="outdoor_run_class"):
    return dict(Uid="1", Did=WATCH_SID, Key=key, Time=str(time), UpdateTime=str(time), GPX=url)


def aggregated_row(tag, key, time, value, sid=WATCH_SID):
    return {**fitness_row(key, time, value, sid), "Tag": tag}


def write_export(root, *, fitness=(), sport=(), tracks=(), aggregated=(), sources=None):
    root.mkdir(parents=True, exist_ok=True)
    sources = (
        sources
        if sources is not None
        else [
            dict(Sid=WATCH_SID, Name="Xiaomi Watch S1 Active   ", Model="midr.watch.k63a"),
            dict(Sid=MANUAL_SID, Name="Add data", Model="mihlth.xiaomi.fitness.manually"),
        ]
    )
    data = dict(
        data_source=sources,
        fitness_data=fitness,
        sport_record=sport,
        sport_track_data=tracks,
        aggregated_fitness_data=aggregated,
    )
    for table, rows in data.items():
        with (root / f"20000101_1_MiFitness_hlth_center_{table}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, HEADERS[table].split())
            w.writeheader()
            w.writerows(rows)
    return root


def load(root, **kwargs):
    from healthviz.xiaomi.devices import load_devices
    from healthviz.xiaomi.source import open_export

    export = open_export(write_export(root, **kwargs))
    return export, load_devices(export)
