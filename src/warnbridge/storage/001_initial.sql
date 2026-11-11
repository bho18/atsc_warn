CREATE TABLE sessions (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, identity TEXT NOT NULL,
 started_at TEXT NOT NULL, ended_at TEXT, state TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE messages (
 id TEXT PRIMARY KEY, protocol TEXT NOT NULL, classification TEXT NOT NULL,
 xml BLOB, fields TEXT NOT NULL, validation TEXT NOT NULL, identity TEXT,
 actual_public INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX messages_class ON messages(classification);
CREATE INDEX messages_identity ON messages(identity);
CREATE TABLE observations (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 message_id TEXT REFERENCES messages(id), processed_at TEXT NOT NULL,
 received_at TEXT, monotonic_ns INTEGER, chunk_index INTEGER NOT NULL,
 transport_id INTEGER, inferred_transport_at TEXT, header BLOB NOT NULL, body BLOB NOT NULL,
 assembled BLOB NOT NULL, raw_ts BLOB NOT NULL, offsets TEXT NOT NULL,
 stored_crc INTEGER, calculated_crc INTEGER, state TEXT NOT NULL, reason TEXT
);
CREATE INDEX observations_message ON observations(message_id);
CREATE INDEX observations_session ON observations(session_id);
CREATE TABLE relationships (
 message_id TEXT NOT NULL REFERENCES messages(id), target_identity TEXT NOT NULL,
 kind TEXT NOT NULL, PRIMARY KEY(message_id, target_identity, kind)
);
CREATE TABLE health_events (
 id INTEGER PRIMARY KEY, session_id TEXT REFERENCES sessions(id),
 at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE web_observations (
 id INTEGER PRIMARY KEY, imported_at TEXT NOT NULL, source TEXT NOT NULL,
 sha256 TEXT NOT NULL, raw_json BLOB NOT NULL, comparison TEXT NOT NULL
);
PRAGMA user_version = 1;
