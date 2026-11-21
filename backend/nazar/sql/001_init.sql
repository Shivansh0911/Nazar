-- Nazar initial schema (BUILD_PROMPT.md section 5)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE cameras (
  id text PRIMARY KEY,                       -- slug, e.g. 'demo', 'hall-1'
  name text NOT NULL,
  source_url text NOT NULL,                  -- file path, rtsp://, srt://, rtmp://
  kind text NOT NULL CHECK (kind IN ('file','rtsp','srt','rtmp','phone')),
  zones jsonb NOT NULL DEFAULT '[]',         -- [{"name":"counter","label":"Counter","polygon":[[x,y],...]}] normalized 0..1
  settings jsonb NOT NULL DEFAULT '{}',      -- per-camera overrides: detect_imgsz, upscale (auto 2 for sources < 720p), detect_conf
  width int, height int,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tracks (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  run_id text NOT NULL,                      -- one per edge run; ByteTrack ids are only unique per run
  local_id int NOT NULL,
  cls text NOT NULL,
  t_start timestamptz NOT NULL,
  t_end timestamptz NOT NULL,
  active boolean NOT NULL DEFAULT true,
  path jsonb NOT NULL DEFAULT '[]',          -- [[t_ms, x1, y1, x2, y2, conf], ...] normalized, 5 Hz
  zone_path text[] NOT NULL DEFAULT '{}',    -- ordered distinct zones visited (derived)
  crop_keys text[] NOT NULL DEFAULT '{}',
  max_conf real,
  appearance vector(76),
  caption text,
  attrs jsonb,
  caption_emb vector(1536),
  enriched boolean NOT NULL DEFAULT false,
  enrich_error text,
  merged_into bigint REFERENCES tracks(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (camera_id, run_id, local_id)
);
CREATE INDEX ON tracks (camera_id, t_start);
CREATE INDEX ON tracks (camera_id, t_end);
CREATE INDEX ON tracks (updated_at);
CREATE INDEX ON tracks USING gin (zone_path);
CREATE INDEX tracks_unenriched ON tracks (t_end) WHERE enriched = false AND active = false;
CREATE INDEX ON tracks USING hnsw (caption_emb vector_cosine_ops);
CREATE INDEX ON tracks USING hnsw (appearance vector_cosine_ops);

CREATE TABLE events (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  track_id bigint NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  type text NOT NULL CHECK (type IN ('enter','exit','dwell')),
  zone text NOT NULL,
  t timestamptz NOT NULL,
  meta jsonb NOT NULL DEFAULT '{}'           -- dwell: {"seconds": 74}
);
CREATE INDEX ON events (camera_id, t);
CREATE INDEX ON events (camera_id, zone, type, t);
CREATE INDEX ON events (track_id);

CREATE TABLE segments (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  t_start timestamptz NOT NULL, t_end timestamptz NOT NULL,
  key text NOT NULL, fps real, width int, height int
);
CREATE INDEX ON segments (camera_id, t_start);

CREATE TABLE camera_status (
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  t timestamptz NOT NULL, ok boolean NOT NULL,
  fps_in real, fps_proc real, active_tracks int, note text
);
CREATE INDEX ON camera_status (camera_id, t);

CREATE TABLE rules (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  text text NOT NULL,                        -- owner's words
  spec jsonb NOT NULL,                       -- validated RuleSpec
  human text NOT NULL,                       -- readable sentence in owner's language
  active boolean NOT NULL DEFAULT false,
  replay jsonb,                              -- {"window_from","window_to","hits":[{track_id,t}], "count"}
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE alerts (
  id bigserial PRIMARY KEY,
  rule_id bigint NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  track_id bigint NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  t timestamptz NOT NULL,
  message text NOT NULL,
  clip_key text, audio_key text, snapshot_key text,
  vision_confirmed boolean,
  ack boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rule_id, track_id)
);

CREATE TABLE queries (
  id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
  camera_id text, input_kind text, transcript text, language text,
  plan jsonb, answer jsonb, latency_ms int, cost_usd numeric(12,6)
);

CREATE TABLE usage (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL,                        -- caption, embed, agent, compile, transcribe, tts, zones, confirm
  model text NOT NULL, camera_id text, ref text,
  input_tokens int, cached_tokens int, output_tokens int, images int, audio_seconds real,
  cost_usd numeric(12,6) NOT NULL DEFAULT 0, unknown_price boolean NOT NULL DEFAULT false
);
CREATE INDEX ON usage (at);

CREATE TABLE jobs (                          -- uploads and demo processing; drives /progress
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  kind text NOT NULL,                        -- upload | demo | recording
  source text NOT NULL, start_time timestamptz,
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','processing','enriching','ready','error')),
  duration_s real, processed_s real NOT NULL DEFAULT 0, error text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
