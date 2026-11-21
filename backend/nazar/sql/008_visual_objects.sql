-- Teach by photo (W4): the owner's (face-blurred) photo of their own scooter/bag is embedded with SigLIP 2 and matched
-- against every newly indexed crop on that camera (local, Rs 0). Matches are Candidates; a rule can alert on them.
ALTER TABLE custom_objects ADD COLUMN IF NOT EXISTS prompt_emb halfvec(768);
ALTER TABLE custom_objects ADD COLUMN IF NOT EXISTS last_checked_id bigint NOT NULL DEFAULT 0;
