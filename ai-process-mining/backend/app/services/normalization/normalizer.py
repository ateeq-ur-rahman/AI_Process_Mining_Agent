"""Event-log normalization. Source values are preserved; normalized values are added."""
from __future__ import annotations

import re

import pandas as pd

_SEP = re.compile(r"[\s_\-]+")


def activity_key(name: str) -> str:
    """Grouping key: case-insensitive, whitespace/underscore/hyphen-insensitive."""
    return _SEP.sub(" ", str(name)).strip().casefold()


def normalize_events(events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Adds `activity` (canonical label) next to `original_activity`.

    The canonical label for each key is the most frequent tidied spelling observed,
    so labels stay recognisable to users. Returns (events, notes).
    """
    df = events.copy()
    df["case_id"] = df["case_id"].astype(str).str.strip()
    tidy = df["original_activity"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    keys = tidy.map(activity_key)
    canonical = (
        pd.DataFrame({"key": keys, "tidy": tidy})
        .groupby(["key", "tidy"]).size().reset_index(name="n")
        .sort_values(["key", "n", "tidy"], ascending=[True, False, True])
        .drop_duplicates("key")
        .set_index("key")["tidy"]
    )
    df["activity"] = keys.map(canonical)
    merged = (
        pd.DataFrame({"key": keys, "orig": df["original_activity"]})
        .groupby("key")["orig"].unique()
    )
    merges = {canonical[k]: sorted(map(str, v)) for k, v in merged.items() if len(v) > 1}
    notes = {"activity_name_merges": merges}
    return df, notes
