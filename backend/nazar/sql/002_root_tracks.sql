-- Stitcher support: retry counter for enrichment, and a view of root tracks that
-- aggregates times and zones of merged children (counting/search use roots only).
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS enrich_attempts int NOT NULL DEFAULT 0;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS job_id bigint REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS zones_updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS note text;
CREATE INDEX IF NOT EXISTS tracks_merged_into ON tracks (merged_into);
CREATE INDEX IF NOT EXISTS segments_camera_end ON segments (camera_id, t_end);
CREATE INDEX IF NOT EXISTS alerts_t ON alerts (t DESC);

CREATE OR REPLACE VIEW root_tracks AS
SELECT t.id, t.camera_id, t.run_id, t.local_id, t.cls,
       LEAST(t.t_start, COALESCE(ch.cmin, t.t_start)) AS t_start,
       GREATEST(t.t_end, COALESCE(ch.cmax, t.t_end)) AS t_end,
       t.active, t.path,
       CASE WHEN ch.zs IS NULL THEN t.zone_path
            ELSE ARRAY(SELECT DISTINCT unnest(t.zone_path || ch.zs)) END AS zone_path,
       t.crop_keys, t.max_conf, t.appearance, t.caption, t.attrs, t.caption_emb,
       t.enriched, t.enrich_error, t.updated_at, COALESCE(ch.n, 0) AS merged_children
FROM tracks t
LEFT JOIN LATERAL (
  SELECT min(c.t_start) AS cmin, max(c.t_end) AS cmax, count(*) AS n,
         (SELECT array_agg(DISTINCT z) FROM tracks c2, unnest(c2.zone_path) z WHERE c2.merged_into = t.id) AS zs
  FROM tracks c WHERE c.merged_into = t.id
) ch ON ch.n > 0
WHERE t.merged_into IS NULL;
