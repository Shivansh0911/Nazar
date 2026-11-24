-- Investigator runs (plan -> execute -> case file) and the actions that wait for the owner's approval.
CREATE TABLE IF NOT EXISTS agent_runs (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  ref text,                                  -- usage.ref of every model call of this run ("inv:...")
  goal text NOT NULL,
  camera_id text,
  trigger text NOT NULL DEFAULT 'user',      -- user | alert | telegram | mcp
  alert_id bigint,
  status text NOT NULL DEFAULT 'running',    -- running | done | error
  plan jsonb NOT NULL DEFAULT '[]',
  result jsonb,
  error text,
  model text,
  latency_ms int,
  cost_usd numeric(12,6),
  query_id bigint
);
CREATE INDEX IF NOT EXISTS agent_runs_created ON agent_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS agent_actions (
  id bigserial PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz,
  tool text NOT NULL,                        -- activate_rule | mcp__<server>__<tool>
  label text NOT NULL,
  args jsonb NOT NULL DEFAULT '{}',
  reason text,
  status text NOT NULL DEFAULT 'pending',    -- pending | running | done | failed | rejected
  result jsonb
);
CREATE INDEX IF NOT EXISTS agent_actions_run ON agent_actions (run_id);
