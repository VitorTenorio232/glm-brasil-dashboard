from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry.base import BaseGeometry

MONTH_NAMES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}
SEASON_ORDER = ["DJF", "MAM", "JJA", "SON"]


def area_km2(geometry: BaseGeometry) -> float:
    gs = gpd.GeoSeries([geometry], crs=4326).to_crs(5880)
    return float(gs.area.iloc[0] / 1_000_000.0)


def filter_by_geometry(flashes: pd.DataFrame, geometry: BaseGeometry) -> pd.DataFrame:
    if flashes.empty:
        return flashes.copy()
    pts = gpd.GeoSeries(gpd.points_from_xy(flashes["lon"], flashes["lat"]), crs=4326)
    # covers inclui pontos exatamente no limite da seleção.
    mask = pts.apply(geometry.covers).to_numpy()
    return flashes.loc[mask].reset_index(drop=True)


def _prepare_time(df: pd.DataFrame, utc_offset_hours: int) -> pd.DataFrame:
    out = df.copy()
    out["time_start"] = pd.to_datetime(out["time_start"], utc=True, errors="coerce")
    out = out[out["time_start"].notna()].copy()
    out["time_local"] = out["time_start"] + pd.Timedelta(hours=utc_offset_hours)
    out["date"] = out["time_local"].dt.floor("D").dt.tz_localize(None)
    out["year"] = out["time_local"].dt.year.astype(int)
    out["month"] = out["time_local"].dt.month.astype(int)
    out["hour"] = out["time_local"].dt.hour.astype(int)
    return out


def _feature_agg(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=group_cols + [
            "flash_count", "mean_energy_j", "median_energy_j", "p95_energy_j", "p99_energy_j", "max_energy_j",
            "mean_area_km2", "median_area_km2", "p95_area_km2", "p99_area_km2", "max_area_km2",
            "mean_duration_ms", "median_duration_ms", "p95_duration_ms", "p99_duration_ms", "max_duration_ms",
        ])

    def q95(x): return x.quantile(.95)
    def q99(x): return x.quantile(.99)

    return df.groupby(group_cols, dropna=False).agg(
        flash_count=("flash_uid", "nunique"),
        mean_energy_j=("energy_j", "mean"),
        median_energy_j=("energy_j", "median"),
        p95_energy_j=("energy_j", q95),
        p99_energy_j=("energy_j", q99),
        max_energy_j=("energy_j", "max"),
        mean_area_km2=("area_km2", "mean"),
        median_area_km2=("area_km2", "median"),
        p95_area_km2=("area_km2", q95),
        p99_area_km2=("area_km2", q99),
        max_area_km2=("area_km2", "max"),
        mean_duration_ms=("duration_ms", "mean"),
        median_duration_ms=("duration_ms", "median"),
        p95_duration_ms=("duration_ms", q95),
        p99_duration_ms=("duration_ms", q99),
        max_duration_ms=("duration_ms", "max"),
    ).reset_index()


def _daily_table(df: pd.DataFrame, start_local: pd.Timestamp, end_local: pd.Timestamp, selection_area_km2: float) -> pd.DataFrame:
    dates = pd.date_range(start_local.normalize().tz_localize(None), end_local.normalize().tz_localize(None), freq="D")
    base = pd.DataFrame({"date": dates})
    agg = _feature_agg(df, ["date"])
    out = base.merge(agg, on="date", how="left")
    out["flash_count"] = out["flash_count"].fillna(0).astype(int)
    out["flash_density_km2"] = out["flash_count"] / selection_area_km2 if selection_area_km2 > 0 else np.nan
    out["lightning_day"] = out["flash_count"] > 0
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    return out


def _monthly_table(df: pd.DataFrame, start_local: pd.Timestamp, end_local: pd.Timestamp, selection_area_km2: float, daily: pd.DataFrame) -> pd.DataFrame:
    periods = pd.period_range(start_local.tz_localize(None).to_period("M"), end_local.tz_localize(None).to_period("M"), freq="M")
    base = pd.DataFrame({"period": periods})
    base["year"] = base["period"].dt.year
    base["month"] = base["period"].dt.month
    agg = _feature_agg(df, ["year", "month"])
    out = base.merge(agg, on=["year", "month"], how="left")
    out["flash_count"] = out["flash_count"].fillna(0).astype(int)
    out["flash_density_km2"] = out["flash_count"] / selection_area_km2 if selection_area_km2 > 0 else np.nan
    days = daily.groupby(["year", "month"], as_index=False).agg(
        lightning_days=("lightning_day", "sum"),
        total_days=("date", "count"),
        max_daily_flashes=("flash_count", "max"),
    )
    out = out.merge(days, on=["year", "month"], how="left")
    out["flashes_per_day"] = out["flash_count"] / out["total_days"].replace(0, np.nan)
    out["flashes_per_active_day"] = out["flash_count"] / out["lightning_days"].replace(0, np.nan)
    out["month_name"] = out["month"].map(MONTH_NAMES)
    out["period_label"] = out["month"].astype(str).str.zfill(2) + "/" + out["year"].astype(str)
    return out


def _annual_table(df: pd.DataFrame, start_local: pd.Timestamp, end_local: pd.Timestamp, selection_area_km2: float, daily: pd.DataFrame) -> pd.DataFrame:
    years = list(range(start_local.year, end_local.year + 1))
    base = pd.DataFrame({"year": years})
    agg = _feature_agg(df, ["year"])
    out = base.merge(agg, on="year", how="left")
    out["flash_count"] = out["flash_count"].fillna(0).astype(int)
    out["flash_density_km2"] = out["flash_count"] / selection_area_km2 if selection_area_km2 > 0 else np.nan
    days = daily.groupby("year", as_index=False).agg(
        lightning_days=("lightning_day", "sum"),
        total_days=("date", "count"),
        max_daily_flashes=("flash_count", "max"),
    )
    out = out.merge(days, on="year", how="left")
    out["flashes_per_day"] = out["flash_count"] / out["total_days"].replace(0, np.nan)
    out["flashes_per_active_day"] = out["flash_count"] / out["lightning_days"].replace(0, np.nan)
    return out


def _hourly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "hour", "flash_count"])
    return df.groupby(["date", "hour"], as_index=False).agg(flash_count=("flash_uid", "nunique"))


def _monthly_climatology(monthly: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "flash_count", "flash_density_km2", "lightning_days", "flashes_per_day",
        "flashes_per_active_day", "mean_duration_ms", "mean_energy_j", "mean_area_km2",
    ]
    rows = []
    for month in range(1, 13):
        g = monthly[monthly["month"] == month]
        row = {"month": month, "month_name": MONTH_NAMES[month], "n_years": int(g["year"].nunique())}
        for metric in metrics:
            if metric in g:
                values = pd.to_numeric(g[metric], errors="coerce")
                row[f"{metric}_mean"] = values.mean()
                row[f"{metric}_median"] = values.median()
                row[f"{metric}_std"] = values.std(ddof=1)
                row[f"{metric}_min"] = values.min()
                row[f"{metric}_max"] = values.max()
        rows.append(row)
    return pd.DataFrame(rows)


def _monthly_anomalies(monthly: pd.DataFrame, clim: pd.DataFrame) -> pd.DataFrame:
    cols = ["month", "flash_count_mean", "flash_count_std", "flash_density_km2_mean", "flash_density_km2_std"]
    cols = [c for c in cols if c in clim.columns]
    out = monthly.merge(clim[cols], on="month", how="left")
    for metric in ["flash_count", "flash_density_km2"]:
        mean = f"{metric}_mean"
        std = f"{metric}_std"
        if mean not in out:
            continue
        out[f"{metric}_anom"] = out[metric] - out[mean]
        out[f"{metric}_anom_pct"] = 100.0 * out[f"{metric}_anom"] / out[mean].replace(0, np.nan)
        if std in out:
            out[f"{metric}_z"] = out[f"{metric}_anom"] / out[std].replace(0, np.nan)
    return out


def _diurnal(df: pd.DataFrame) -> pd.DataFrame:
    base = pd.DataFrame({"hour": list(range(24))})
    if df.empty:
        base["flash_count"] = 0
    else:
        counts = df.groupby("hour")["flash_uid"].nunique().rename("flash_count").reset_index()
        base = base.merge(counts, on="hour", how="left")
        base["flash_count"] = base["flash_count"].fillna(0).astype(int)
    total = base["flash_count"].sum()
    base["fraction_pct"] = 100 * base["flash_count"] / total if total else 0.0
    base["period"] = np.where(base["hour"].between(6, 17), "Diurno (06–18)", "Noturno (18–06)")
    return base


def _day_night(diurnal: pd.DataFrame) -> pd.DataFrame:
    out = diurnal.groupby("period", as_index=False)["flash_count"].sum()
    total = out["flash_count"].sum()
    out["fraction_pct"] = 100 * out["flash_count"] / total if total else 0.0
    return out


def _seasonality(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_month = monthly.groupby("month", as_index=False).agg(
        total_flashes=("flash_count", "sum"),
        mean_monthly_flashes=("flash_count", "mean"),
        mean_lightning_days=("lightning_days", "mean"),
    )
    base = pd.DataFrame({"month": list(range(1, 13))})
    by_month = base.merge(by_month, on="month", how="left").fillna(0)
    by_month["month_name"] = by_month["month"].map(MONTH_NAMES)
    total = by_month["total_flashes"].sum()
    by_month["fraction_pct"] = 100 * by_month["total_flashes"] / total if total else 0.0

    def season(month):
        if month in (12, 1, 2): return "DJF"
        if month in (3, 4, 5): return "MAM"
        if month in (6, 7, 8): return "JJA"
        return "SON"

    temp = monthly.copy()
    temp["season"] = temp["month"].map(season)
    by_season = temp.groupby("season", as_index=False).agg(
        total_flashes=("flash_count", "sum"),
        mean_monthly_flashes=("flash_count", "mean"),
        mean_lightning_days=("lightning_days", "mean"),
    )
    by_season["season"] = pd.Categorical(by_season["season"], SEASON_ORDER, ordered=True)
    by_season = by_season.sort_values("season").reset_index(drop=True)
    total_s = by_season["total_flashes"].sum()
    by_season["fraction_pct"] = 100 * by_season["total_flashes"] / total_s if total_s else 0.0
    return by_month, by_season


def _feature_summary(series: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {k: np.nan for k in ["mean", "median", "std", "p90", "p95", "p99", "max"]}
    return {
        "mean": float(s.mean()), "median": float(s.median()), "std": float(s.std(ddof=1)),
        "p90": float(s.quantile(.90)), "p95": float(s.quantile(.95)),
        "p99": float(s.quantile(.99)), "max": float(s.max()),
    }


def _rankings(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    tmp = df.copy()
    tmp["date_text"] = tmp["date"].astype(str)
    state = tmp[tmp["abbrev_state"].notna()].groupby("abbrev_state", as_index=False).agg(
        flash_count=("flash_uid", "nunique"),
        lightning_days=("date_text", "nunique"),
    ).sort_values(["flash_count", "abbrev_state"], ascending=[False, True]).reset_index(drop=True)
    if not state.empty:
        state.insert(0, "rank", range(1, len(state) + 1))
        total = state["flash_count"].sum()
        state["fraction_pct"] = 100 * state["flash_count"] / total if total else 0.0

    muni_cols = ["code_muni", "name_muni", "abbrev_state"]
    valid = tmp[tmp["code_muni"].notna()].copy()
    muni = valid.groupby(muni_cols, as_index=False).agg(
        flash_count=("flash_uid", "nunique"),
        lightning_days=("date_text", "nunique"),
        area_muni_km2=("area_muni_km2", "first"),
    )
    if not muni.empty:
        muni["flash_density_km2"] = muni["flash_count"] / muni["area_muni_km2"].replace(0, np.nan)
        muni = muni.sort_values(["flash_count", "name_muni"], ascending=[False, True]).reset_index(drop=True)
        muni.insert(0, "rank", range(1, len(muni) + 1))
        total = muni["flash_count"].sum()
        muni["fraction_pct"] = 100 * muni["flash_count"] / total if total else 0.0
    return state, muni


def municipality_month_profile(monthly: pd.DataFrame) -> pd.DataFrame:
    clim = _monthly_climatology(monthly)
    total_by_month = monthly.groupby("month", as_index=False)["flash_count"].sum().rename(columns={"flash_count": "total_flashes"})
    out = clim.merge(total_by_month, on="month", how="left")
    out["total_flashes"] = out["total_flashes"].fillna(0).astype(int)
    denom = out["flash_count_mean"].sum()
    out["climatological_fraction_pct"] = 100 * out["flash_count_mean"] / denom if denom else 0.0
    return out


@dataclass
class AnalysisProducts:
    flashes: pd.DataFrame
    daily: pd.DataFrame
    monthly: pd.DataFrame
    annual: pd.DataFrame
    hourly: pd.DataFrame
    monthly_climatology: pd.DataFrame
    monthly_anomalies: pd.DataFrame
    diurnal: pd.DataFrame
    day_night: pd.DataFrame
    seasonality_month: pd.DataFrame
    seasonality_season: pd.DataFrame
    ranking_states: pd.DataFrame
    ranking_municipalities: pd.DataFrame
    municipality_months: pd.DataFrame
    summary: dict
    feature_summary: dict


def calculate_analysis(
    flashes: pd.DataFrame,
    *,
    start,
    end,
    selection_area_km2: float,
    utc_offset_hours: int = -3,
) -> AnalysisProducts:
    start_utc = pd.Timestamp(start)
    end_utc = pd.Timestamp(end)
    if start_utc.tzinfo is None:
        start_utc = start_utc.tz_localize("UTC")
    else:
        start_utc = start_utc.tz_convert("UTC")
    if end_utc.tzinfo is None:
        end_utc = end_utc.tz_localize("UTC")
    else:
        end_utc = end_utc.tz_convert("UTC")

    df = _prepare_time(flashes, utc_offset_hours)
    # Proteção caso repositório tenha retornado intervalo maior.
    df = df[(df["time_start"] >= start_utc) & (df["time_start"] <= end_utc)].copy()

    start_local = start_utc + pd.Timedelta(hours=utc_offset_hours)
    end_local = end_utc + pd.Timedelta(hours=utc_offset_hours)

    daily = _daily_table(df, start_local, end_local, selection_area_km2)
    monthly = _monthly_table(df, start_local, end_local, selection_area_km2, daily)
    annual = _annual_table(df, start_local, end_local, selection_area_km2, daily)
    hourly = _hourly(df)
    mclim = _monthly_climatology(monthly)
    anomalies = _monthly_anomalies(monthly, mclim)
    diurnal = _diurnal(df)
    day_night = _day_night(diurnal)
    smonth, sseason = _seasonality(monthly)
    rank_state, rank_muni = _rankings(df)
    muni_months = municipality_month_profile(monthly)

    total = int(df["flash_uid"].nunique()) if not df.empty else 0
    active_days = int(daily["lightning_day"].sum())
    total_days = int(len(daily))
    max_daily = int(daily["flash_count"].max()) if len(daily) else 0
    max_daily_date = daily.loc[daily["flash_count"].idxmax(), "date"] if len(daily) else None
    if not hourly.empty:
        ih = hourly["flash_count"].idxmax()
        max_hourly = int(hourly.loc[ih, "flash_count"])
        max_hourly_date = hourly.loc[ih, "date"]
        max_hourly_hour = int(hourly.loc[ih, "hour"])
    else:
        max_hourly = 0; max_hourly_date = None; max_hourly_hour = None

    summary = {
        "flash_count": total,
        "area_km2": float(selection_area_km2),
        "flash_density_km2": total / selection_area_km2 if selection_area_km2 > 0 else np.nan,
        "lightning_days": active_days,
        "total_days": total_days,
        "flashes_per_day": total / total_days if total_days else np.nan,
        "flashes_per_active_day": total / active_days if active_days else np.nan,
        "max_daily_flashes": max_daily,
        "max_daily_date": max_daily_date,
        "max_hourly_flashes": max_hourly,
        "max_hourly_date": max_hourly_date,
        "max_hourly_hour": max_hourly_hour,
    }
    feature_summary = {
        "duration_ms": _feature_summary(df["duration_ms"]) if "duration_ms" in df else {},
        "energy_j": _feature_summary(df["energy_j"]) if "energy_j" in df else {},
        "area_km2": _feature_summary(df["area_km2"]) if "area_km2" in df else {},
    }
    return AnalysisProducts(
        flashes=df, daily=daily, monthly=monthly, annual=annual, hourly=hourly,
        monthly_climatology=mclim, monthly_anomalies=anomalies,
        diurnal=diurnal, day_night=day_night,
        seasonality_month=smonth, seasonality_season=sseason,
        ranking_states=rank_state, ranking_municipalities=rank_muni,
        municipality_months=muni_months, summary=summary,
        feature_summary=feature_summary,
    )
