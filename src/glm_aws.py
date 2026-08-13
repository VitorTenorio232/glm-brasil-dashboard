from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Iterable

from .config import GLM_PRODUCT, GOES19_OPERATIONAL_UTC

_START_RE = re.compile(r"_s(?P<stamp>\d{14})")  # YYYYJJJHHMMSSd (décimo de segundo)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def satellite_for_datetime(dt: datetime) -> str:
    """GOES-East operacional usado pelo projeto."""
    dt = ensure_utc(dt)
    return "16" if dt < GOES19_OPERATIONAL_UTC else "19"


def bucket_for_satellite(goes: str) -> str:
    if str(goes) not in {"16", "19"}:
        raise ValueError("Este projeto usa GOES-East: satélites 16 ou 19.")
    return f"noaa-goes{goes}"


def hour_prefix(dt: datetime, goes: str | None = None) -> tuple[str, str]:
    dt = ensure_utc(dt)
    goes = goes or satellite_for_datetime(dt)
    prefix = f"{GLM_PRODUCT}/{dt:%Y}/{dt:%j}/{dt:%H}/"
    return bucket_for_satellite(goes), prefix


def parse_key_start_time(key: str) -> datetime | None:
    m = _START_RE.search(key)
    if not m:
        return None
    stamp = m.group("stamp")
    # 4 ano + 3 DOY + 2 hora + 2 minuto + 2 segundo + 1 décimo
    base = datetime.strptime(stamp[:13], "%Y%j%H%M%S").replace(tzinfo=timezone.utc)
    return base + timedelta(milliseconds=int(stamp[13]) * 100)


def iter_hours(start: datetime, end: datetime) -> Iterable[datetime]:
    start = ensure_utc(start).replace(minute=0, second=0, microsecond=0)
    end = ensure_utc(end)
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(hours=1)


def unsigned_s3_client():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client(
        "s3",
        config=Config(signature_version=UNSIGNED, retries={"max_attempts": 5, "mode": "standard"}),
        region_name="us-east-1",
    )


def list_hour_keys(client, hour: datetime) -> list[tuple[str, str, datetime]]:
    """Lista uma hora do GLM no bucket; retorna (bucket, key, start_time)."""
    goes = satellite_for_datetime(hour)
    bucket, prefix = hour_prefix(hour, goes)
    paginator = client.get_paginator("list_objects_v2")
    out: list[tuple[str, str, datetime]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            ts = parse_key_start_time(key)
            if ts is not None:
                out.append((bucket, key, ts))
    return out


@dataclass
class DownloadResult:
    requested_start: datetime
    requested_end: datetime
    files_found: int
    files_downloaded: int
    files_existing: int
    manifest: list[dict]


def download_period(
    start: datetime,
    end: datetime,
    dest: str | Path,
    *,
    client=None,
    overwrite: bool = False,
) -> DownloadResult:
    """Baixa GLM-L2-LCFA listando o S3 por hora (mais eficiente que 1 chamada/20 s)."""
    start, end = ensure_utc(start), ensure_utc(end)
    if end < start:
        raise ValueError("end precisa ser >= start")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    client = client or unsigned_s3_client()

    selected: list[tuple[str, str, datetime]] = []
    for hour in iter_hours(start, end):
        selected.extend(
            item for item in list_hour_keys(client, hour)
            if start <= item[2] <= end
        )
    selected.sort(key=lambda x: x[2])

    downloaded = existing = 0
    manifest: list[dict] = []
    for bucket, key, ts in selected:
        target = dest / Path(key).name
        status = "existing"
        if overwrite or not target.exists():
            client.download_file(bucket, key, str(target))
            downloaded += 1
            status = "downloaded"
        else:
            existing += 1
        manifest.append({
            "timestamp_utc": ts.isoformat(),
            "satellite": f"G{satellite_for_datetime(ts)}",
            "bucket": bucket,
            "key": key,
            "local_file": str(target),
            "status": status,
        })

    return DownloadResult(start, end, len(selected), downloaded, existing, manifest)
