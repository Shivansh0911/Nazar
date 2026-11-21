-- Nazar v2 (BUILD_PROMPT_V2.md section E): originals, local visual index, line counters, security events,
-- custom objects, audit, feedback, reports, Telegram, camera credentials, service tier.

-- Files are no longer re-encoded: the original stays on disk and clips are cut (and blurred) from it on demand.
CREATE TABLE IF NOT EXISTS originals (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  path text NOT NULL,                      -- absolute local path (never served)
  t_start timestamptz NOT NULL, t_end timestamptz NOT NULL,
  width int, height int, fps real, rotation int NOT NULL DEFAULT 0,
  job_id bigint REFERENCES jobs(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS originals_cam_t ON originals (camera_id, t_start);

-- Path points may now carry a head box: [t_ms,x1,y1,x2,y2,conf,hx1,hy1,hx2,hy2] (old 6-element points stay valid).
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS vis_emb halfvec(768);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS quality real;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS custom_object_id bigint;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS vis_indexed boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS tracks_vis_emb ON tracks USING hnsw (vis_emb halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS tracks_vis_pending ON tracks (id) WHERE vis_indexed = false AND active = false;

CREATE TABLE IF NOT EXISTS keyframes (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  t timestamptz NOT NULL,
  key text NOT NULL,                       -- face-blurred 512 px JPEG
  persons int NOT NULL DEFAULT 0,
  emb halfvec(768)
);
CREATE INDEX IF NOT EXISTS keyframes_cam_t ON keyframes (camera_id, t);
CREATE INDEX IF NOT EXISTS keyframes_emb ON keyframes USING hnsw (emb halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS keyframes_pending ON keyframes (id) WHERE emb IS NULL;

-- Line counters produce cross_in / cross_out events.
ALTER TABLE events DROP CONSTRAINT IF EXISTS events_type_check;
ALTER TABLE events ADD CONSTRAINT events_type_check CHECK (type IN ('enter','exit','dwell','cross_in','cross_out'));

CREATE TABLE IF NOT EXISTS sec_events (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  type text NOT NULL,                      -- loitering, abandoned_object, object_removed, running, fall, crowding, after_hours, possible_snatch, wrong_way
  t_start timestamptz NOT NULL, t_end timestamptz NOT NULL,
  track_ids bigint[] NOT NULL DEFAULT '{}',
  level text NOT NULL DEFAULT 'candidate' CHECK (level IN ('confirmed','probable','candidate')),
  verified_by text, reason text,
  meta jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (camera_id, type, t_start, track_ids)
);
CREATE INDEX IF NOT EXISTS sec_events_cam_t ON sec_events (camera_id, t_start);

CREATE TABLE IF NOT EXISTS custom_objects (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  name text NOT NULL,
  prompt_type text NOT NULL CHECK (prompt_type IN ('text','visual')),
  prompt_text text, prompt_image_key text, prompt_box jsonb,
  threshold real NOT NULL DEFAULT 0.25,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (camera_id, name)
);

CREATE TABLE IF NOT EXISTS photo_searches (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  purpose text, image_key text, params jsonb NOT NULL DEFAULT '{}', result_count int
);

CREATE TABLE IF NOT EXISTS feedback (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL, ref text NOT NULL, correct boolean NOT NULL, note text,
  UNIQUE (kind, ref)
);

CREATE TABLE IF NOT EXISTS reports (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  title text NOT NULL, language text NOT NULL DEFAULT 'en',
  pdf_key text, manifest_sha256 text, source jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS telegram_chats (
  chat_id bigint PRIMARY KEY, paired_at timestamptz NOT NULL DEFAULT now(),
  name text, language text, alerts boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS kv (k text PRIMARY KEY, v jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS camera_credentials (
  camera_id text PRIMARY KEY REFERENCES cameras(id) ON DELETE CASCADE,
  enc_username text, enc_password text
);
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS brand text;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS location text;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS ip text;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS port int;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS channel int;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS stream text;

ALTER TABLE usage ADD COLUMN IF NOT EXISTS service_tier text;
ALTER TABLE queries ADD COLUMN IF NOT EXISTS model text;
ALTER TABLE queries ADD COLUMN IF NOT EXISTS first_text_ms int;
