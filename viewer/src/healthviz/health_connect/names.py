"""Health Connect enum names (androidx.health.connect.client 1.1.0, library-private tables)."""

EXERCISE_TYPES = {
    0: "workout",
    2: "badminton",
    4: "baseball",
    5: "basketball",
    8: "biking",
    9: "biking_stationary",
    10: "boot_camp",
    11: "boxing",
    13: "calisthenics",
    14: "cricket",
    16: "dancing",
    25: "elliptical",
    26: "exercise_class",
    27: "fencing",
    28: "football_american",
    29: "football_australian",
    31: "frisbee_disc",
    32: "golf",
    33: "guided_breathing",
    34: "gymnastics",
    35: "handball",
    36: "high_intensity_interval_training",
    37: "hiking",
    38: "ice_hockey",
    39: "ice_skating",
    44: "martial_arts",
    46: "paddling",
    47: "para_gliding",
    48: "pilates",
    50: "racquetball",
    51: "rock_climbing",
    52: "roller_hockey",
    53: "rowing",
    54: "rowing_machine",
    55: "rugby",
    56: "running",
    57: "running_treadmill",
    58: "sailing",
    59: "scuba_diving",
    60: "skating",
    61: "skiing",
    62: "snowboarding",
    63: "snowshoeing",
    64: "soccer",
    65: "softball",
    66: "squash",
    68: "stair_climbing",
    69: "stair_climbing_machine",
    70: "strength_training",
    71: "stretching",
    72: "surfing",
    73: "swimming_open_water",
    74: "swimming_pool",
    75: "table_tennis",
    76: "tennis",
    78: "volleyball",
    79: "walking",
    80: "water_polo",
    81: "weightlifting",
    82: "wheelchair",
    83: "yoga",
}
OTHER_WORKOUT = 0
SLEEP_STAGES = {
    0: "unknown",
    1: "awake",
    2: "sleeping",
    3: "out_of_bed",
    4: "light",
    5: "deep",
    6: "rem",
    7: "awake_in_bed",
}
ARCHIVE_STAGES = {1: "awake", 3: "awake", 7: "awake", 4: "light", 5: "deep", 6: "rem"}


def exercise_name(code: int) -> str:
    """Health Connect's name, or the number when this table predates it."""
    return EXERCISE_TYPES.get(code, str(code))


def workout_type(code: int) -> str:
    """Generic and unknown types become other_workout, as in the Xiaomi importer."""
    return "other_workout" if code == OTHER_WORKOUT else EXERCISE_TYPES.get(code, "other_workout")


def stage_name(code: int) -> str:
    return SLEEP_STAGES.get(code, str(code))


def archive_stage(code: int) -> str:
    return ARCHIVE_STAGES.get(code, "unknown")
