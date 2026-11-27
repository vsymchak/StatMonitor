"""
StatMonitor - Cold Odds Archive (SPEC-39: Wave 12).
Автоматичне збереження часових рядів котирувань перед 4-денною ротацією odds_history
у компактні Parquet-файли на Cloudflare R2 (S3-compatible) або локальне сховище.
"""

import os
import io
import hashlib
import hmac
import json
from datetime import datetime, timezone
import requests

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None

try:
    import pandas as pd
except ImportError:
    pd = None

from statmonitor.config import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    R2_ENDPOINT_URL,
    LOCAL_ARCHIVE_DIR,
)
from statmonitor.database import get_cols


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(key, date_stamp, region_name, service_name):
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def upload_to_r2(
    data_bytes: bytes,
    object_key: str,
    bucket_name: str = None,
    content_type: str = "application/vnd.apache.parquet",
    timeout: int = 30,
) -> tuple[bool, str, str]:
    """
    Завантажує бінарний файл Parquet на Cloudflare R2 через SigV4 S3 API.
    Якщо R2 облікові дані не налаштовані, зберігає локально в LOCAL_ARCHIVE_DIR.
    Повертає (success, target_uri, storage_type).
    """
    bucket = bucket_name or R2_BUCKET_NAME or "statmonitor-cold-archive"
    acc_id = R2_ACCOUNT_ID
    key_id = R2_ACCESS_KEY_ID
    secret = R2_SECRET_ACCESS_KEY
    endpoint = R2_ENDPOINT_URL

    # Якщо R2 налаштовано - виконуємо завантаження через SigV4
    if key_id and secret and (endpoint or acc_id):
        if not endpoint and acc_id:
            endpoint = f"https://{acc_id}.r2.cloudflarestorage.com"
        
        endpoint = endpoint.rstrip("/")
        import urllib.parse
        encoded_bucket = urllib.parse.quote(str(bucket).strip("/"), safe="")
        encoded_key = urllib.parse.quote(str(object_key).lstrip("/"), safe="/")
        # URL: https://<endpoint>/<bucket>/<object_key>
        put_url = f"{endpoint}/{encoded_bucket}/{encoded_key}"

        now_utc = datetime.now(timezone.utc)
        amz_date = now_utc.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now_utc.strftime("%Y%m%d")
        region = "auto"
        service = "s3"

        host = endpoint.replace("https://", "").replace("http://", "").split("/")[0]
        canonical_uri = f"/{encoded_bucket}/{encoded_key}"

        payload_hash = hashlib.sha256(data_bytes).hexdigest()

        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
        canonical_request = (
            f"PUT\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        )

        signing_key = _get_signature_key(secret, date_stamp, region, service)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = (
            f"AWS4-HMAC-SHA256 Credential={key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Content-Type": content_type,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": auth_header,
        }

        try:
            resp = requests.put(put_url, data=data_bytes, headers=headers, timeout=timeout)
            if resp.status_code in (200, 201):
                return True, f"r2://{bucket}/{object_key}", "R2"
            else:
                print(f"⚠️ R2 upload HTTP {resp.status_code}: {resp.text[:150]}, fallback to local.")
        except Exception as e:
            print(f"⚠️ R2 upload exception: {e}, fallback to local.")

    # Локальний фолбек (Local Storage)
    base_dir = LOCAL_ARCHIVE_DIR or "archive/parquet"
    local_path = os.path.join(base_dir, object_key.replace("/", os.sep))
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data_bytes)
    return True, f"local://{os.path.abspath(local_path)}", "LOCAL"


def records_to_parquet_bytes(records: list[dict], compression: str = "snappy") -> bytes:
    """Конвертує список словників у бінарний Parquet-файл за допомогою pyarrow / pandas."""
    if not records:
        return b""
    buf = io.BytesIO()
    if pa is not None and pq is not None:
        table = pa.Table.from_pylist(records)
        pq.write_table(table, buf, compression=compression)
        return buf.getvalue()
    elif pd is not None:
        df = pd.DataFrame(records)
        df.to_parquet(buf, index=False, engine="pyarrow", compression=compression)
        return buf.getvalue()
    else:
        raise ImportError("pyarrow or pandas is required to write Parquet files.")


def ensure_archive_tables(cur):
    """Створює таблицю cold_archive_manifest за необхідності."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cold_archive_manifest (
            id SERIAL PRIMARY KEY,
            partition_date DATE NOT NULL,
            storage_type TEXT NOT NULL DEFAULT 'R2',
            file_path TEXT NOT NULL,
            file_size_bytes BIGINT NOT NULL DEFAULT 0,
            records_count INT NOT NULL DEFAULT 0,
            checksum_sha256 TEXT,
            min_recorded_at TIMESTAMPTZ,
            max_recorded_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata JSONB DEFAULT '{}'::jsonb,
            CONSTRAINT uq_cold_archive_partition_path UNIQUE (partition_date, file_path)
        );
        CREATE INDEX IF NOT EXISTS idx_cold_archive_partition_date ON cold_archive_manifest (partition_date DESC);
        CREATE INDEX IF NOT EXISTS idx_cold_archive_archived_at ON cold_archive_manifest (archived_at DESC);
    """)


def archive_cold_odds(
    cur,
    conn,
    min_age_days: float = 3.5,
    batch_limit: int = 50000,
    bucket_name: str = None,
) -> dict:
    """
    Знаходить котирування в odds_history, старші за min_age_days,
    групує їх за датою (partition_date), експортує у стислі Parquet-файли,
    завантажує у Cloudflare R2 (або локально) та реєструє в cold_archive_manifest.
    """
    ensure_archive_tables(cur)

    oh_cols = get_cols(cur, "odds_history")
    time_col = "recorded_at" if "recorded_at" in oh_cols else ("created_at" if "created_at" in oh_cols else None)
    if not time_col:
        return {"success": False, "error": "No time column in odds_history", "total_records": 0, "files_created": 0}

    # Вибірка даних перед ротацією (параметризований SQL)
    sql = f"""
        SELECT 
            oh.id,
            oh.event_id,
            COALESCE(e.sport, 'unknown') AS sport,
            COALESCE(e.match_name, '') AS match_name,
            e.commence_time,
            oh.bookmaker,
            COALESCE(oh.market_key, 'h2h') AS market_key,
            COALESCE(oh.outcome_name, '') AS outcome_name,
            oh.point,
            oh.price,
            oh.{time_col} AS recorded_at
        FROM odds_history oh
        LEFT JOIN events e ON oh.event_id = e.id
        WHERE oh.{time_col} < NOW() - (INTERVAL '1 day' * %s)
        ORDER BY oh.{time_col} ASC
        LIMIT %s;
    """
    cur.execute(sql, (float(min_age_days), int(batch_limit)))
    rows = cur.fetchall()
    if not rows:
        return {"success": True, "total_records": 0, "files_created": 0, "partitions": []}

    cols = [
        "id", "event_id", "sport", "match_name", "commence_time",
        "bookmaker", "market_key", "outcome_name", "point", "price", "recorded_at"
    ]
    raw_records = [dict(zip(cols, r)) for r in rows]

    # Групуємо за календарною датою recorded_at (UTC)
    partitions_map = {}
    for r in raw_records:
        rec_time = r.get("recorded_at")
        if rec_time:
            if isinstance(rec_time, datetime):
                p_date = rec_time.strftime("%Y-%m-%d")
            else:
                p_date = str(rec_time)[:10]
        else:
            p_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if p_date not in partitions_map:
            partitions_map[p_date] = []
        partitions_map[p_date].append(r)

    files_created = 0
    total_bytes = 0
    created_manifests = []

    for p_date, p_rows in partitions_map.items():
        if not p_rows:
            continue

        try:
            dt = datetime.strptime(p_date, "%Y-%m-%d")
            year_str = dt.strftime("%Y")
            month_str = dt.strftime("%m")
        except Exception:
            year_str = "2026"
            month_str = "11"

        obj_key = f"odds_history/year={year_str}/month={month_str}/odds_{p_date.replace('-', '_')}.parquet"
        pq_bytes = records_to_parquet_bytes(p_rows)
        if not pq_bytes:
            continue

        sha256_hash = hashlib.sha256(pq_bytes).hexdigest()
        file_size = len(pq_bytes)

        ok_up, file_uri, st_type = upload_to_r2(pq_bytes, obj_key, bucket_name=bucket_name)

        min_rec = min((r["recorded_at"] for r in p_rows if r.get("recorded_at")), default=None)
        max_rec = max((r["recorded_at"] for r in p_rows if r.get("recorded_at")), default=None)

        # Фіксація в маніфесті
        cur.execute("""
            INSERT INTO cold_archive_manifest 
                (partition_date, storage_type, file_path, file_size_bytes, records_count, checksum_sha256, min_recorded_at, max_recorded_at, metadata)
            VALUES 
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (partition_date, file_path) 
            DO UPDATE SET 
                file_size_bytes = EXCLUDED.file_size_bytes,
                records_count = EXCLUDED.records_count,
                checksum_sha256 = EXCLUDED.checksum_sha256,
                min_recorded_at = EXCLUDED.min_recorded_at,
                max_recorded_at = EXCLUDED.max_recorded_at,
                archived_at = NOW(),
                metadata = EXCLUDED.metadata;
        """, (
            p_date,
            st_type,
            file_uri,
            file_size,
            len(p_rows),
            sha256_hash,
            min_rec,
            max_rec,
            json.dumps({"object_key": obj_key, "format": "parquet", "compression": "snappy"})
        ))

        files_created += 1
        total_bytes += file_size
        created_manifests.append({
            "partition_date": p_date,
            "file_uri": file_uri,
            "storage_type": st_type,
            "records": len(p_rows),
            "size_bytes": file_size,
        })

    conn.commit()

    return {
        "success": True,
        "total_records": len(raw_records),
        "files_created": files_created,
        "total_bytes": total_bytes,
        "partitions": created_manifests,
    }


def get_cold_archive_summary(cur) -> dict:
    """Повертає статистику та останні збережені файли з cold_archive_manifest."""
    try:
        cur.execute("""
            SELECT 
                COUNT(*) as files_count,
                COALESCE(SUM(records_count), 0) as total_records,
                COALESCE(SUM(file_size_bytes), 0) as total_bytes,
                MAX(partition_date) as latest_partition,
                MAX(archived_at) as latest_archive_time
            FROM cold_archive_manifest;
        """)
        row = cur.fetchone()
        files_cnt = int(row[0] or 0)
        tot_records = int(row[1] or 0)
        tot_bytes = int(row[2] or 0)
        latest_p = str(row[3]) if row[3] else None
        latest_t = row[4]

        # Останні 15 збережених файлів
        cur.execute("""
            SELECT id, partition_date, storage_type, file_path, file_size_bytes, records_count, checksum_sha256, archived_at
            FROM cold_archive_manifest
            ORDER BY partition_date DESC, archived_at DESC
            LIMIT 15;
        """)
        history = [
            {
                "id": r[0],
                "partition_date": str(r[1]),
                "storage_type": r[2],
                "file_path": r[3],
                "file_size_bytes": r[4],
                "file_size_kb": round((r[4] or 0) / 1024.0, 1),
                "records_count": r[5],
                "checksum_sha256": r[6],
                "archived_at": r[7],
            }
            for r in cur.fetchall()
        ]

        return {
            "has_data": files_cnt > 0,
            "files_count": files_cnt,
            "total_records": tot_records,
            "total_bytes": tot_bytes,
            "total_mb": round(tot_bytes / (1024.0 * 1024.0), 2),
            "latest_partition": latest_p,
            "latest_archive_time": latest_t,
            "recent_files": history,
        }
    except Exception as e:
        return {
            "has_data": False,
            "files_count": 0,
            "total_records": 0,
            "total_bytes": 0,
            "total_mb": 0.0,
            "latest_partition": None,
            "latest_archive_time": None,
            "recent_files": [],
            "error": str(e),
        }
