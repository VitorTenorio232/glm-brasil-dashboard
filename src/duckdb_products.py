from __future__ import annotations
from pathlib import Path


def build_duckdb_products(parquet_glob: str, out_dir: str | Path):
    import duckdb
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect()
    glob_sql=parquet_glob.replace("'","''")
    con.execute(f"""
    CREATE OR REPLACE VIEW f0 AS SELECT * FROM read_parquet('{glob_sql}', hive_partitioning=true);
    CREATE OR REPLACE VIEW f AS
    SELECT *,
      CAST(time_start AS DATE) AS obs_date,
      EXTRACT(YEAR FROM time_start)::INTEGER AS yy,
      EXTRACT(MONTH FROM time_start)::INTEGER AS mm,
      EXTRACT(HOUR FROM time_start)::INTEGER AS hh
    FROM f0 WHERE code_muni IS NOT NULL;
    """)
    key="code_muni, name_muni, abbrev_state, area_muni_km2"
    def copy(name,sql):
        path=(out_dir/f"{name}.parquet").as_posix().replace("'","''")
        con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD)")

    hourly=f"""SELECT {key}, yy AS year, mm AS month, obs_date AS date, hh AS hour,
    COUNT(DISTINCT flash_uid) AS flash_count FROM f GROUP BY ALL"""
    copy("hourly",hourly)
    daily=f"""SELECT {key}, yy AS year, mm AS month, obs_date AS date,
    COUNT(DISTINCT flash_uid) AS flash_count,
    COUNT(DISTINCT flash_uid)/NULLIF(area_muni_km2,0) AS flash_density_km2,
    AVG(energy_j) mean_energy_j, MEDIAN(energy_j) median_energy_j,
    QUANTILE_CONT(energy_j,.95) p95_energy_j, QUANTILE_CONT(energy_j,.99) p99_energy_j, MAX(energy_j) max_energy_j,
    AVG(area_km2) mean_area_km2, MEDIAN(area_km2) median_area_km2,
    QUANTILE_CONT(area_km2,.95) p95_area_km2, QUANTILE_CONT(area_km2,.99) p99_area_km2, MAX(area_km2) max_area_km2,
    AVG(duration_ms) mean_duration_ms, MEDIAN(duration_ms) median_duration_ms,
    QUANTILE_CONT(duration_ms,.95) p95_duration_ms, QUANTILE_CONT(duration_ms,.99) p99_duration_ms, MAX(duration_ms) max_duration_ms
    FROM f GROUP BY ALL"""
    copy("daily",daily)
    con.execute(f"CREATE OR REPLACE VIEW daily AS {daily}")
    con.execute(f"CREATE OR REPLACE VIEW hourly AS {hourly}")

    def period_sql(period):
        dims="yy AS year, mm AS month" if period=="monthly" else "yy AS year"
        group_dims="year, month" if period=="monthly" else "year"
        daily_join="d.year=m.year AND d.month=m.month" if period=="monthly" else "d.year=m.year"
        hourly_join="h.year=m.year AND h.month=m.month" if period=="monthly" else "h.year=m.year"
        return f"""
        WITH m AS (
          SELECT {key}, {dims}, COUNT(DISTINCT flash_uid) flash_count,
          COUNT(DISTINCT flash_uid)/NULLIF(area_muni_km2,0) flash_density_km2,
          COUNT(DISTINCT obs_date) lightning_days,
          AVG(energy_j) mean_energy_j, MEDIAN(energy_j) median_energy_j,
          QUANTILE_CONT(energy_j,.95) p95_energy_j, QUANTILE_CONT(energy_j,.99) p99_energy_j, MAX(energy_j) max_energy_j,
          AVG(area_km2) mean_area_km2, MEDIAN(area_km2) median_area_km2,
          QUANTILE_CONT(area_km2,.95) p95_area_km2, QUANTILE_CONT(area_km2,.99) p99_area_km2, MAX(area_km2) max_area_km2,
          AVG(duration_ms) mean_duration_ms, MEDIAN(duration_ms) median_duration_ms,
          QUANTILE_CONT(duration_ms,.95) p95_duration_ms, QUANTILE_CONT(duration_ms,.99) p99_duration_ms, MAX(duration_ms) max_duration_ms
          FROM f GROUP BY ALL
        ), d AS (SELECT code_muni,{group_dims},MAX(flash_count) max_daily_flashes FROM daily GROUP BY ALL),
        h AS (SELECT code_muni,{group_dims},MAX(flash_count) max_hourly_flashes FROM hourly GROUP BY ALL)
        SELECT m.*,d.max_daily_flashes,h.max_hourly_flashes,
          m.flash_count/NULLIF(m.lightning_days,0) flashes_per_active_day
        FROM m LEFT JOIN d ON d.code_muni=m.code_muni AND {daily_join}
        LEFT JOIN h ON h.code_muni=m.code_muni AND {hourly_join}
        """
    monthly=period_sql("monthly"); annual=period_sql("annual")
    copy("monthly",monthly); copy("annual",annual)
    con.execute(f"CREATE OR REPLACE VIEW monthly AS {monthly}")
    con.execute(f"CREATE OR REPLACE VIEW annual AS {annual}")

    copy("diurnal",f"""SELECT {key}, yy year, mm month, hh hour, COUNT(DISTINCT flash_uid) flash_count,
      100.0*COUNT(DISTINCT flash_uid)/SUM(COUNT(DISTINCT flash_uid)) OVER(PARTITION BY code_muni,yy,mm) hourly_fraction_pct
      FROM f GROUP BY ALL""")
    copy("monthly_climatology",f"""SELECT {key},month,
      AVG(flash_count) flash_count_mean, MEDIAN(flash_count) flash_count_median, STDDEV_SAMP(flash_count) flash_count_std,
      AVG(flash_density_km2) flash_density_km2_mean, MEDIAN(flash_density_km2) flash_density_km2_median, STDDEV_SAMP(flash_density_km2) flash_density_km2_std,
      AVG(lightning_days) lightning_days_mean, MEDIAN(lightning_days) lightning_days_median, STDDEV_SAMP(lightning_days) lightning_days_std,
      AVG(max_daily_flashes) max_daily_flashes_mean, AVG(max_hourly_flashes) max_hourly_flashes_mean,
      AVG(mean_energy_j) mean_energy_j_mean, AVG(mean_area_km2) mean_area_km2_mean, AVG(mean_duration_ms) mean_duration_ms_mean,
      COUNT(DISTINCT year) n_years FROM monthly GROUP BY ALL""")
    mclim_path = (out_dir / "monthly_climatology.parquet").as_posix().replace("\'", "\'\'")
    con.execute(f"CREATE OR REPLACE VIEW mclim AS SELECT * FROM read_parquet('{mclim_path}')")
    copy("monthly_anomalies","""SELECT m.*,c.flash_count_mean,c.flash_count_std,c.flash_density_km2_mean,c.flash_density_km2_std,
      m.flash_count-c.flash_count_mean flash_count_anom,
      100.0*(m.flash_count-c.flash_count_mean)/NULLIF(c.flash_count_mean,0) flash_count_anom_pct,
      (m.flash_count-c.flash_count_mean)/NULLIF(c.flash_count_std,0) flash_count_z,
      m.flash_density_km2-c.flash_density_km2_mean flash_density_km2_anom,
      100.0*(m.flash_density_km2-c.flash_density_km2_mean)/NULLIF(c.flash_density_km2_mean,0) flash_density_km2_anom_pct,
      (m.flash_density_km2-c.flash_density_km2_mean)/NULLIF(c.flash_density_km2_std,0) flash_density_km2_z
      FROM monthly m JOIN mclim c USING(code_muni,name_muni,abbrev_state,area_muni_km2,month)""")
    copy("annual_climatology",f"""SELECT {key},
      AVG(flash_count) flash_count_mean, MEDIAN(flash_count) flash_count_median, STDDEV_SAMP(flash_count) flash_count_std,
      AVG(flash_density_km2) flash_density_km2_mean, MEDIAN(flash_density_km2) flash_density_km2_median, STDDEV_SAMP(flash_density_km2) flash_density_km2_std,
      AVG(lightning_days) lightning_days_mean, COUNT(DISTINCT year) n_years FROM annual GROUP BY ALL""")
    copy("records","""WITH rd AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY code_muni ORDER BY flash_count DESC,date) rn FROM daily),
      rh AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY code_muni ORDER BY flash_count DESC,date,hour) rn FROM hourly)
      SELECT rd.code_muni,rd.name_muni,rd.abbrev_state,rd.flash_count record_daily_flashes,rd.date record_daily_date,
      rh.flash_count record_hourly_flashes,rh.date record_hourly_date,rh.hour record_hourly_hour
      FROM rd JOIN rh USING(code_muni) WHERE rd.rn=1 AND rh.rn=1""")
    con.close()
