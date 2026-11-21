-- Footage coverage = live recordings (segments) + registered originals (files are no longer re-encoded).
CREATE OR REPLACE VIEW coverage AS
SELECT camera_id, t_start, t_end, 'segment'::text AS kind FROM segments
UNION ALL
SELECT camera_id, t_start, t_end, 'original'::text AS kind FROM originals;
