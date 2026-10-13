from zoneinfo import ZoneInfo

from healthviz.xiaomi.offsets import OffsetResolver

ROME = ZoneInfo("Europe/Rome")


def test_dst_boundary():
    resolver = OffsetResolver(ROME, [(1774728000, 60)])
    assert resolver.minutes_at(1774744200) == 60
    assert resolver.minutes_at(1774747800) == 120


def test_travel_and_no_anchor():
    resolver = OffsetResolver(ROME, [(1767268800, 300)])
    assert resolver.minutes_at(1767268800 + 7200) == 300
    assert resolver.minutes_at(1767268800 + 3 * 86400) == 60
    assert OffsetResolver(ROME, []).minutes_at(1767225600) == 60
