CREATE TABLE receiver_status (
 session_id TEXT PRIMARY KEY REFERENCES sessions(id),
 checked_at TEXT NOT NULL, host TEXT NOT NULL, tuner INTEGER NOT NULL,
 raw_status TEXT, error TEXT
);
CREATE INDEX observations_state_id ON observations(state, id);
PRAGMA user_version = 2;
