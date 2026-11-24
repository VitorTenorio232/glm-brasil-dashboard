"""Compara download_file (HeadObject + GetObject) com get_object (só GetObject) nos arquivos GLM recentes.

Uso: python bench_download.py <repo> [n_arquivos] [rodadas]
Cada rodada baixa os mesmos n arquivos numa pasta vazia, alternando os dois métodos.
"""
import collections
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, sys.argv[1])
N = int(sys.argv[2]) if len(sys.argv) > 2 else 90
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 2

import botocore.client  # noqa: E402

from src.glm_aws import unsigned_s3_client  # noqa: E402
from src.glm_reader import read_glm_files  # noqa: E402
from src.realtime_glm import _list_recent_keys  # noqa: E402

lock = threading.Lock()
calls = collections.Counter()
orig = botocore.client.BaseClient._make_api_call


def api(self, op, params):
    with lock:
        calls[op] += 1
    return orig(self, op, params)


botocore.client.BaseClient._make_api_call = api

client = unsigned_s3_client()
keys = _list_recent_keys(client, datetime.now(timezone.utc))[-N:]
print("arquivos:", len(keys), flush=True)


def via_download_file(bucket, key, target):
    client.download_file(bucket, key, str(target))


def via_get_object(bucket, key, target):
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    with open(target, "wb") as fh:
        shutil.copyfileobj(body, fh, 1024 * 1024)


results = collections.defaultdict(list)
for r in range(ROUNDS):
    for name, fn in (("download_file", via_download_file), ("get_object", via_get_object)):
        tmp = Path(tempfile.mkdtemp(prefix="fv_bench_"))
        calls.clear()
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda k: fn(k[0], k[1], tmp / Path(k[1]).name), keys))
        dt = time.perf_counter() - t0
        size = sum(p.stat().st_size for p in tmp.iterdir()) / 1e6
        df = read_glm_files(sorted(tmp.iterdir()), quality="zero_only")
        results[name].append(dt)
        print(f"rodada {r + 1} {name:<14} {dt:6.2f} s  {size:6.1f} MB  chamadas={dict(calls)}  flashes={len(df)}",
              flush=True)
        shutil.rmtree(tmp, ignore_errors=True)

for name, values in results.items():
    print(f"{name:<14} média {sum(values) / len(values):.2f} s  ({', '.join(f'{v:.2f}' for v in values)})")
