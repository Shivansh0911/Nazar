-- Read-only semantic layer for analytics_query (W6.2). The agent may only SELECT from these views, as role nazar_ro.
CREATE OR REPLACE VIEW v_cameras AS
SELECT id AS camera_id, name, kind, location, brand FROM cameras;

-- root tracks (stitched ID fragments merged); counted = the "people seen" rule (>= 1.5 s, max conf >= 0.6)
CREATE OR REPLACE VIEW v_tracks AS
SELECT r.id AS track_id, r.camera_id, r.cls, r.t_start, r.t_end,
       round(extract(epoch FROM r.t_end - r.t_start)::numeric, 1) AS duration_s,
       r.zone_path AS zones, r.max_conf, r.caption,
       (r.t_end - r.t_start >= interval '1.5 seconds' AND COALESCE(r.max_conf, 1) >= 0.6) AS counted
FROM root_tracks r WHERE NOT r.active OR r.t_end > now() - interval '1 minute';

CREATE OR REPLACE VIEW v_events AS
SELECT e.id AS event_id, e.camera_id, COALESCE(t.merged_into, t.id) AS track_id, t.cls, e.type, e.zone, e.t,
       NULLIF(e.meta->>'seconds', '')::real AS dwell_s
FROM events e JOIN tracks t ON t.id = e.track_id;

CREATE OR REPLACE VIEW v_crossings AS
SELECT event_id, camera_id, track_id, cls, zone AS line, CASE WHEN type = 'cross_in' THEN 'in' ELSE 'out' END AS direction, t
FROM v_events WHERE type IN ('cross_in', 'cross_out');

CREATE OR REPLACE VIEW v_alerts AS
SELECT a.id AS alert_id, a.rule_id, a.camera_id, a.t, a.message, r.text AS rule_text, a.ack
FROM alerts a JOIN rules r ON r.id = a.rule_id;

CREATE OR REPLACE VIEW v_hourly AS
SELECT camera_id, cls, date_trunc('hour', t_start AT TIME ZONE 'Asia/Kolkata') AS hour_local, count(*) AS tracks
FROM v_tracks WHERE counted GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW v_sec_events AS
SELECT id AS sec_event_id, camera_id, type, t_start, t_end, level, reason FROM sec_events;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nazar_ro') THEN
    CREATE ROLE nazar_ro LOGIN PASSWORD 'nazar_ro' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM nazar_ro;
GRANT USAGE ON SCHEMA public TO nazar_ro;
GRANT SELECT ON v_cameras, v_tracks, v_events, v_crossings, v_alerts, v_hourly, v_sec_events TO nazar_ro;
ALTER ROLE nazar_ro SET statement_timeout = '5s';
ALTER ROLE nazar_ro SET default_transaction_read_only = on;
ALTER ROLE nazar_ro SET timezone = 'Asia/Kolkata';
