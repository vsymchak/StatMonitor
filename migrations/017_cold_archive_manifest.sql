-- 017_cold_archive_manifest.sql
-- SPEC-39: Реєстр холодного архіву котирувань Parquet (Cloudflare R2 / S3)

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
