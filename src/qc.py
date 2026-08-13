from __future__ import annotations

from pathlib import Path
import pandas as pd
from .glm_aws import parse_key_start_time

FILES_PER_DAY = 24 * 60 * 3  # ~20 s


def inventory_raw_files(paths) -> pd.DataFrame:
    rows = []
    for p in map(Path, paths):
        ts = parse_key_start_time(p.name)
        rows.append({"source_file": p.name, "timestamp_utc": ts})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out[out["timestamp_utc"].notna()].copy()
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True)
    out["date"] = out["timestamp_utc"].dt.date.astype(str)
    out["year"] = out["timestamp_utc"].dt.year
    out["month"] = out["timestamp_utc"].dt.month
    return out


def completeness_tables(paths) -> tuple[pd.DataFrame, pd.DataFrame]:
    inv = inventory_raw_files(paths)
    if inv.empty:
        return pd.DataFrame(), pd.DataFrame()
    daily = inv.groupby(["year", "month", "date"]).agg(files_found=("source_file", "nunique")).reset_index()
    daily["files_expected"] = FILES_PER_DAY
    daily["completeness_pct"] = 100 * daily["files_found"] / daily["files_expected"]
    monthly = daily.groupby(["year", "month"]).agg(
        files_found=("files_found", "sum"), files_expected=("files_expected", "sum")
    ).reset_index()
    monthly["completeness_pct"] = 100 * monthly["files_found"] / monthly["files_expected"]
    return daily, monthly


def quality_summary(flashes: pd.DataFrame) -> pd.DataFrame:
    if flashes.empty or "quality_flag" not in flashes:
        return pd.DataFrame()
    return (
        flashes.assign(quality_flag=flashes["quality_flag"].fillna(-9999))
        .groupby("quality_flag")
        .size().rename("flash_count").reset_index()
    )
