"""Overview by area: key numbers against the user's usual, one chart per area."""

import streamlit as st

from healthviz.analysis.usual import (
    changes,
    compare_daily,
    compare_nights,
    compare_point_readings,
    compare_weekly_total,
)
from healthviz.dashboard.charts import daily_figure, filtered, raw_data, show_number
from healthviz.dashboard.context import derived, open_page
from healthviz.dashboard.format import (
    bpm,
    clock_text,
    count_text,
    kcal,
    kg,
    km,
    minutes_text,
    percent,
)


def key_numbers(context, nights):
    """Area → (label, comparison, value text, difference text, measured noun)."""
    daily, start, end = context.daily, context.start, context.end

    def night(column, **options):
        return compare_nights(nights, column, start, end, **options)

    def day(metric):
        return compare_daily(daily, metric, start, end)

    return {
        "Sleep": [
            ("Asleep per night", night("sleep_min"), minutes_text, minutes_text, "nights"),
            ("Deep sleep", night("deep_min"), minutes_text, minutes_text, "nights"),
            ("REM sleep", night("rem_min"), minutes_text, minutes_text, "nights"),
            ("Bedtime", night("onset_wall_min", clock=True), clock_text, minutes_text, "nights"),
        ],
        "Heart": [
            ("Resting heart rate", day("resting_hr"), bpm, bpm, "days"),
            (
                "Blood oxygen",
                compare_point_readings(daily, "spo2", start, end),
                percent,
                percent,
                "readings",
            ),
        ],
        "Activity": [
            ("Steps per day", day("steps"), count_text, count_text, "days"),
            ("Active energy per day", day("active_kcal"), kcal, kcal, "days"),
            ("Distance per day", day("distance"), km, km, "days"),
            (
                "Workout time per week",
                compare_weekly_total(daily, "workout_min", start, end),
                minutes_text,
                minutes_text,
                "days",
            ),
        ],
        "Body": [
            ("Weight", compare_point_readings(daily, "weight", start, end), kg, kg, "readings")
        ],
    }


# Area → (daily metric, unit, scale, bars) for the chart beside the key numbers.
CHARTS = {
    "Sleep": ("sleep_min", "hours", 1 / 60, False),
    "Heart": ("resting_hr", "bpm", 1, False),
    "Activity": ("steps", "steps", 1, True),
    "Body": ("weight", "kg", 1, False),
}


def section(context, area, numbers):
    metric, unit, scale, bars = CHARTS[area]
    with st.container(border=True):
        st.subheader(area)
        left, right = st.columns([1, 2])
        with left:
            grid = st.columns(2)
            for index, number in enumerate(numbers):
                with grid[index % 2]:
                    show_number(*number)
            st.button(f"{area} details →", on_click=open_page, args=(area,), key="open-" + area)
        with right:
            usual = numbers[0][1].usual
            figure = daily_figure(
                context.daily,
                metric,
                context.start,
                context.end,
                usual,
                unit,
                bars=bars,
                scale=scale,
            )
            st.plotly_chart(figure, width="stretch", key="overview-" + area)


def render(context):
    nights, _ = derived(context)
    numbers = key_numbers(context, nights)
    # Bedtime has no above/below; it stays out of the banner.
    candidates = {
        label: (label, result, change_text)
        for area in numbers.values()
        for label, result, _, change_text, _ in area
        if label != "Bedtime"
    }
    st.info("What changed  \n" + "  \n".join(f"- {line}" for line in changes(candidates)))
    for area, area_numbers in numbers.items():
        section(context, area, area_numbers)
    raw_data({"Daily overview": filtered(context.daily, context.start, context.end)})
