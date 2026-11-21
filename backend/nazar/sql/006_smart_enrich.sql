-- ENRICH_MODE=smart: captions only for tracks someone needs (opened, verified, alerts, incidents).
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS enrich_requested boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS tracks_enrich_requested ON tracks (id) WHERE enrich_requested AND NOT enriched;
-- Every AI verification of a search hit is recorded; only a recorded "yes" can make a hit Probable.
CREATE TABLE IF NOT EXISTS verifications (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  question text NOT NULL, kind text NOT NULL CHECK (kind IN ('track','keyframe','sec_event')),
  ref_id bigint NOT NULL, match text NOT NULL CHECK (match IN ('yes','no','unclear')),
  reason text, sim real, usage_ref text
);
CREATE INDEX IF NOT EXISTS verifications_ref ON verifications (kind, ref_id);
