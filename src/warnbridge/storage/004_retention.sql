CREATE TABLE IF NOT EXISTS observation_sequence (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_id INTEGER NOT NULL
);
INSERT OR IGNORE INTO observation_sequence SELECT 1,coalesce(max(id),0) FROM observations;
CREATE TABLE IF NOT EXISTS maintenance_status (
 kind TEXT PRIMARY KEY, at TEXT NOT NULL, details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_processed ON observations(processed_at);
PRAGMA user_version = 4;
