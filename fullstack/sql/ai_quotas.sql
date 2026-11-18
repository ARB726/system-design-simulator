-- Apply with a database administrator before enabling shared AI access.
-- This schema must NOT be added to the Supabase Data API's exposed schemas.
CREATE SCHEMA IF NOT EXISTS lab_private;
REVOKE ALL ON SCHEMA lab_private FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS lab_private.ai_usage (
  "window" BIGINT NOT NULL,
  subject VARCHAR(64) NOT NULL,
  attempts INTEGER NOT NULL CHECK (attempts >= 0),
  PRIMARY KEY ("window", subject)
);
CREATE TABLE IF NOT EXISTS lab_private.ai_cache (
  key VARCHAR(64) PRIMARY KEY,
  owner VARCHAR(254) NOT NULL,
  response TEXT,
  expires BIGINT NOT NULL,
  lease_token VARCHAR(32),
  lease_until BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_private.ai_slots (
  id INTEGER PRIMARY KEY CHECK (id IN (0, 1)),
  token VARCHAR(32) NOT NULL,
  expires BIGINT NOT NULL
);
REVOKE ALL ON ALL TABLES IN SCHEMA lab_private FROM PUBLIC, anon, authenticated;
-- Grant USAGE on lab_private and SELECT/INSERT/UPDATE/DELETE on these three
-- tables only to the dedicated backend database role. Never expose its password.
