"""Sleep detail: stages per night, timing, the selected night and every night of the period."""

import pandas as pd
import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.observations import onset_sd, sleep_observations
from healthviz.analysis.usual import compare_nights
from healthviz.dashboard.charts import (
    clock_figure,
    filtered,
    hypnogram,
    notes,
    overlap_audit,
    raw_data,
    show_number,
    stages_figure,
)
from healthviz.dashboard.context import derived, device_names, open_page, remember, restore
from healthviz.dashboard.format import clock_text, day_text, minutes_text


def duration(value) -> str:
    return "—" if value is None or pd.isna(value) else minutes_text(value)


def key_numbers(nights, eligible, start, end):
    per_night, deep, rem, bedtime, measured = st.columns(5)
    asleep = compare_nights(nights, "sleep_min", start, end)
    with per_night:
        show_number("Per night", asleep, minutes_text, minutes_text)
    with deep:
        show_number("Deep", compare_nights(nights, "deep_min", start, end), duration, minutes_text)
    with rem:
        show_number("REM", compare_nights(nights, "rem_min", start, end), duration, minutes_text)
    with bedtime:
        onset = compare_nights(nights, "onset_wall_min", start, end, clock=True)
        show_number("Bedtime", onset, clock_text, minutes_text)
        if len(eligible) > 1:
            st.caption(f"varies ±{minutes_text(onset_sd(eligible.onset_wall_min))}")
    with measured:
        st.metric("Nights measured", f"{asleep.counted} / {asleep.total}")
        st.caption(f"{asleep.total - asleep.counted} missing or incomplete")
    return asleep


def selected_night(main, stages):
    """A night picked by date; the options change with the period, so a stale pick cannot stay."""
    if main.empty:
        st.info("No nights recorded in this period.")
        return
    by_day = main.set_index("date_local")
    restore("night", by_day.index)
    day = st.selectbox(
        "Night",
        list(by_day.index),
        key="night",
        format_func=lambda d: f"{day_text(d)} · {duration(by_day.loc[d, 'sleep_min'])}",
    )
    remember("night", day)
    night = by_day.loc[day]
    st.subheader(f"Selected night · {day_text(day)}")
    st.caption(
        f"{clock_text(night.onset_wall_min)} → {clock_text(night.wake_wall_min)} · "
        f"{duration(night.sleep_min)} asleep"
    )
    hypnogram({**night.to_dict(), "date_local": day}, stages)
    st.button("Open this day →", on_click=open_page, args=("Day",), kwargs={"day": day})


def nights_list(main, start, end, names) -> pd.DataFrame:
    by_day = main.set_index("date_local")
    rows = []
    for day in reversed(pd.date_range(start, end).date):
        if day not in by_day.index:
            rows.append({"Night": day_text(day), "Asleep": "—", "Note": "not measured"})
            continue
        night = by_day.loc[day]
        rows.append(
            {
                "Night": day_text(day),
                "Asleep": duration(night.sleep_min),
                "From → to": f"{clock_text(night.onset_wall_min)} → "
                f"{clock_text(night.wake_wall_min)}",
                **{
                    stage.title() if stage != "rem" else "REM": duration(night.get(f"{stage}_min"))
                    for stage in ("deep", "light", "rem", "awake")
                },
                "Source": names.get(night.device_id, night.device_id),
                "Note": "" if night.eligible else "incomplete · not in averages",
            }
        )
    columns = ["Night", "Asleep", "From → to", "Deep", "Light", "REM", "Awake", "Source", "Note"]
    return pd.DataFrame(rows, columns=columns).fillna("")


def render(context):
    daily, start, end = context.daily, context.start, context.end
    st.button("← Overview", on_click=open_page, args=("Overview",))
    nights, _ = derived(context)
    main = filtered(nights.loc[nights.main.astype(bool)], start, end).sort_values(
        "date_local", ascending=False
    )
    eligible = main.loc[main.eligible.astype(bool)].sort_values("date_local")
    asleep = key_numbers(nights, eligible, start, end)
    st.plotly_chart(stages_figure(eligible, asleep.usual), width="stretch", key="sleep-stages")
    st.caption("Recorded stages per night · nights not measured or incomplete are left out.")
    timing, night = st.columns(2)
    with timing:
        st.plotly_chart(clock_figure(eligible), width="stretch", key="sleep-clock")
        st.caption("Each bar goes from falling asleep to waking up, local time.")
    with night:
        selected_night(main, context.tables["sleep_stages"])
    st.subheader("Nights")
    st.dataframe(nights_list(main, start, end, device_names(context)), hide_index=True)
    notes(sleep_observations(daily, nights, end))
    period = filtered(daily, start, end)
    raw_data(
        {
            "Sleep sessions and naps": filtered(nights, start, end),
            "Sleep week summaries": period_summary(period, "week"),
            "Sleep month summaries": period_summary(period, "month"),
            "Sleep source overlaps": overlap_audit(context, "sleep_sessions"),
        }
    )
