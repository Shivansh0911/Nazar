-- Rules remember the owner's language and when they were activated (live alerts only fire for hits after that);
-- alerts keep hit details (zone, actor/object track) for the UI and clip cutting.
ALTER TABLE rules ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'en';
ALTER TABLE rules ADD COLUMN IF NOT EXISTS activated_at timestamptz;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS camera_id text REFERENCES cameras(id) ON DELETE CASCADE;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS meta jsonb NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS rules_active ON rules (camera_id) WHERE active;
