-- cl_optimizations.sql
-- Recommended database optimisations for photoschat
-- Run on MINI (PostgreSQL 18.1) as the postgres user
-- ──────────────────────────────────────────────────────────────────────

-- 1. COVERING INDEX for the main search query
--    Avoids heap fetches for the most-used sort column.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_photos_date_taken_desc
    ON photos (date_taken DESC NULLS LAST);

-- 2. COMPOSITE INDEX for camera + lens searches (frequently paired)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_photos_camera_lens
    ON photos (camera_model, lens_model);

-- 3. TRIGRAM INDEX on pathname for ILIKE searches
--    The existing idx_caption_trgm covers caption; pathname needs its own.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pathname_trgm
    ON photos USING gin (pathname public.gin_trgm_ops);

-- 4. TRIGRAM INDEXES on other ILIKE-searched text columns
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aperture_trgm
    ON photos USING gin (aperture public.gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_shutter_speed_trgm
    ON photos USING gin (shutter_speed public.gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_focal_length_trgm
    ON photos USING gin (focal_length public.gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_camera_model_trgm
    ON photos USING gin (camera_model public.gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lens_model_trgm
    ON photos USING gin (lens_model public.gin_trgm_ops);

-- 5. SWITCH face_embedding from IVFFlat to HNSW
--    HNSW gives better recall without needing periodic re-clustering.
--    The photos.embedding index already uses HNSW; align face_embedding.
DROP INDEX IF EXISTS idx_face_embedding;
CREATE INDEX CONCURRENTLY idx_face_embedding_hnsw
    ON photos USING hnsw (face_embedding public.vector_cosine_ops);

-- 6. HNSW on photo_faces.embedding (currently unindexed)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_photo_faces_embedding_hnsw
    ON photo_faces USING hnsw (embedding public.vector_cosine_ops);

-- 7. DUPLICATE VECTOR INDEX cleanup
--    photos has BOTH an IVFFlat (photos_embedding_idx) and an HNSW
--    (idx_photos_embedding) on the same column.  Keep only HNSW.
DROP INDEX IF EXISTS photos_embedding_idx;

-- 8. STATISTICS for better planner estimates on wide text columns
ALTER TABLE photos ALTER COLUMN pathname SET STATISTICS 500;
ALTER TABLE photos ALTER COLUMN caption  SET STATISTICS 500;
ANALYZE photos;

-- 9. CONNECTION POOLING recommendation (not SQL — note for ops)
--    With 16 cores on MINI, set max_connections = 100 and deploy
--    PgBouncer in transaction mode on MINI to multiplex client
--    connections from WINNIESACERPC.

-- 10. SHARED_BUFFERS / WORK_MEM tuning (postgresql.conf on MINI)
--     shared_buffers = 8GB        (25% of 32 GB)
--     effective_cache_size = 24GB (75% of 32 GB)
--     work_mem = 64MB             (for sorts / hash joins)
--     maintenance_work_mem = 1GB  (for VACUUM, CREATE INDEX)
--     random_page_cost = 1.1      (SSD storage assumed)
