from __future__ import annotations

import numpy as np
import pandas as pd

KEYS = ["code_muni", "name_muni", "abbrev_state", "area_muni_km2"]


def add_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time_start"] = pd.to_datetime(out["time_start"], utc=True)
    out["date"] = out["time_start"].dt.date.astype(str)
    out["year"] = out["time_start"].dt.year.astype(int)
    out["month"] = out["time_start"].dt.month.astype(int)
    out["day"] = out["time_start"].dt.day.astype(int)
    out["hour"] = out["time_start"].dt.hour.astype(int)
    return out


def _q(s, q):
    return s.quantile(q) if len(s) else np.nan


def aggregate_period(flashes: pd.DataFrame, period: str) -> pd.DataFrame:
    """period: daily | monthly | annual"""
    df = add_time_columns(flashes)
    if period == "daily":
        group = KEYS + ["year", "month", "date"]
    elif period == "monthly":
        group = KEYS + ["year", "month"]
    elif period == "annual":
        group = KEYS + ["year"]
    else:
        raise ValueError(period)

    out = df.groupby(group, dropna=False).agg(
        flash_count=("flash_uid", "nunique"),
        mean_energy_j=("energy_j", "mean"),
        median_energy_j=("energy_j", "median"),
        p95_energy_j=("energy_j", lambda x: _q(x, .95)),
        p99_energy_j=("energy_j", lambda x: _q(x, .99)),
        max_energy_j=("energy_j", "max"),
        mean_area_km2=("area_km2", "mean"),
        median_area_km2=("area_km2", "median"),
        p95_area_km2=("area_km2", lambda x: _q(x, .95)),
        p99_area_km2=("area_km2", lambda x: _q(x, .99)),
        max_area_km2=("area_km2", "max"),
        mean_duration_ms=("duration_ms", "mean"),
        median_duration_ms=("duration_ms", "median"),
        p95_duration_ms=("duration_ms", lambda x: _q(x, .95)),
        p99_duration_ms=("duration_ms", lambda x: _q(x, .99)),
        max_duration_ms=("duration_ms", "max"),
    ).reset_index()
    out["flash_density_km2"] = out["flash_count"] / out["area_muni_km2"].replace(0, np.nan)

    if period in {"monthly", "annual"}:
        day_cols = KEYS + (["year", "month"] if period == "monthly" else ["year"])
        days = df.groupby(day_cols)["date"].nunique().rename("lightning_days").reset_index()
        out = out.merge(days, on=day_cols, how="left")

        daily = aggregate_period(flashes, "daily")
        max_daily = daily.groupby(day_cols)["flash_count"].max().rename("max_daily_flashes").reset_index()
        out = out.merge(max_daily, on=day_cols, how="left")

        hourly = aggregate_hourly(flashes)
        max_hourly = hourly.groupby(day_cols)["flash_count"].max().rename("max_hourly_flashes").reset_index()
        out = out.merge(max_hourly, on=day_cols, how="left")
        out["flashes_per_active_day"] = out["flash_count"] / out["lightning_days"].replace(0, np.nan)
    return out


def aggregate_hourly(flashes: pd.DataFrame) -> pd.DataFrame:
    df = add_time_columns(flashes)
    group = KEYS + ["year", "month", "date", "hour"]
    return df.groupby(group, dropna=False).agg(flash_count=("flash_uid", "nunique")).reset_index()


def diurnal_cycle(flashes: pd.DataFrame) -> pd.DataFrame:
    df = add_time_columns(flashes)
    group = KEYS + ["year", "month", "hour"]
    out = df.groupby(group).agg(flash_count=("flash_uid", "nunique")).reset_index()
    totals = out.groupby(KEYS + ["year", "month"])["flash_count"].transform("sum")
    out["hourly_fraction_pct"] = 100 * out["flash_count"] / totals.replace(0, np.nan)
    return out


def monthly_climatology(monthly: pd.DataFrame) -> pd.DataFrame:
    group = KEYS + ["month"]
    metrics = [
        "flash_count", "flash_density_km2", "lightning_days", "max_daily_flashes",
        "max_hourly_flashes", "mean_energy_j", "mean_area_km2", "mean_duration_ms"
    ]
    agg = {m: ["mean", "median", "std"] for m in metrics if m in monthly.columns}
    out = monthly.groupby(group).agg(agg)
    out.columns = [f"{c}_{stat}" for c, stat in out.columns]
    out = out.reset_index()
    years = monthly.groupby(group)["year"].nunique().rename("n_years").reset_index()
    return out.merge(years, on=group, how="left")


def annual_climatology(annual: pd.DataFrame) -> pd.DataFrame:
    group = KEYS
    metrics = [
        "flash_count", "flash_density_km2", "lightning_days", "max_daily_flashes",
        "max_hourly_flashes", "mean_energy_j", "mean_area_km2", "mean_duration_ms"
    ]
    agg = {m: ["mean", "median", "std"] for m in metrics if m in annual.columns}
    out = annual.groupby(group).agg(agg)
    out.columns = [f"{c}_{stat}" for c, stat in out.columns]
    out = out.reset_index()
    years = annual.groupby(group)["year"].nunique().rename("n_years").reset_index()
    return out.merge(years, on=group, how="left")


def monthly_anomalies(monthly: pd.DataFrame, clim: pd.DataFrame) -> pd.DataFrame:
    keys = KEYS + ["month"]
    cols = keys + [c for c in clim.columns if c.startswith("flash_count_") or c.startswith("flash_density_km2_")]
    out = monthly.merge(clim[cols], on=keys, how="left")
    for metric in ["flash_count", "flash_density_km2"]:
        mean = f"{metric}_mean"
        std = f"{metric}_std"
        out[f"{metric}_anom"] = out[metric] - out[mean]
        out[f"{metric}_anom_pct"] = 100 * out[f"{metric}_anom"] / out[mean].replace(0, np.nan)
        out[f"{metric}_z"] = out[f"{metric}_anom"] / out[std].replace(0, np.nan)
    return out


def records(daily: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for code, g in daily.groupby("code_muni"):
        imax = g["flash_count"].idxmax()
        r = g.loc[imax]
        h = hourly[hourly["code_muni"] == code]
        if not h.empty:
            ih = h["flash_count"].idxmax()
            rh = h.loc[ih]
        else:
            rh = None
        rows.append({
            "code_muni": code,
            "name_muni": r["name_muni"],
            "abbrev_state": r["abbrev_state"],
            "record_daily_flashes": int(r["flash_count"]),
            "record_daily_date": r["date"],
            "record_hourly_flashes": int(rh["flash_count"]) if rh is not None else np.nan,
            "record_hourly_date": rh["date"] if rh is not None else None,
            "record_hourly_hour": int(rh["hour"]) if rh is not None else np.nan,
        })
    return pd.DataFrame(rows)


def build_products(flashes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    flashes = flashes[flashes["code_muni"].notna()].copy()
    daily = aggregate_period(flashes, "daily")
    monthly = aggregate_period(flashes, "monthly")
    annual = aggregate_period(flashes, "annual")
    hourly = aggregate_hourly(flashes)
    diurnal = diurnal_cycle(flashes)
    mclim = monthly_climatology(monthly)
    aclim = annual_climatology(annual)
    anomalies = monthly_anomalies(monthly, mclim)
    rec = records(daily, hourly)
    return {
        "flashes_enriched": flashes,
        "daily": daily,
        "monthly": monthly,
        "annual": annual,
        "hourly": hourly,
        "diurnal": diurnal,
        "monthly_climatology": mclim,
        "annual_climatology": aclim,
        "monthly_anomalies": anomalies,
        "records": rec,
    }
