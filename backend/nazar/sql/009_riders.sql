-- v3 #5: motorcycle/bicycle riders are not "people on foot". rider_of = the vehicle track they rode.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS rider_of bigint;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS rider_checked boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS tracks_rider_pending ON tracks (id) WHERE NOT rider_checked AND cls = 'person';

CREATE OR REPLACE VIEW root_tracks AS
SELECT t.id, t.camera_id, t.run_id, t.local_id, t.cls,
       LEAST(t.t_start, COALESCE(ch.cmin, t.t_start)) AS t_start,
       GREATEST(t.t_end, COALESCE(ch.cmax, t.t_end)) AS t_end,
       t.active, t.path,
       CASE WHEN ch.zs IS NULL THEN t.zone_path
            ELSE ARRAY(SELECT DISTINCT unnest(t.zone_path || ch.zs)) END AS zone_path,
       t.crop_keys, t.max_conf, t.appearance, t.caption, t.attrs, t.caption_emb,
       t.enriched, t.enrich_error, t.updated_at, COALESCE(ch.n, 0) AS merged_children, t.rider_of
FROM tracks t
LEFT JOIN LATERAL (
  SELECT min(c.t_start) AS cmin, max(c.t_end) AS cmax, count(*) AS n,
         (SELECT array_agg(DISTINCT z) FROM tracks c2, unnest(c2.zone_path) z WHERE c2.merged_into = t.id) AS zs
  FROM tracks c WHERE c.merged_into = t.id
) ch ON ch.n > 0
WHERE t.merged_into IS NULL;

-- counted = people seen (>= 1.5 s, conf >= 0.6) and, for persons, not a rider; rider = rode a motorcycle/bicycle
CREATE OR REPLACE VIEW v_tracks AS
SELECT r.id AS track_id, r.camera_id, r.cls, r.t_start, r.t_end,
       round(extract(epoch FROM r.t_end - r.t_start)::numeric, 1) AS duration_s,
       r.zone_path AS zones, r.max_conf, r.caption,
       (r.t_end - r.t_start >= interval '1.5 seconds' AND COALESCE(r.max_conf, 1) >= 0.6 AND r.rider_of IS NULL) AS counted,
       (r.rider_of IS NOT NULL) AS rider
FROM root_tracks r WHERE NOT r.active OR r.t_end > now() - interval '1 minute';
