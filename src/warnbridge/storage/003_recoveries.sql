CREATE TABLE observation_recoveries (
 observation_id INTEGER PRIMARY KEY REFERENCES observations(id),
 recovered_at TEXT NOT NULL,
 original_reason TEXT NOT NULL,
 original_header BLOB NOT NULL,
 original_body BLOB NOT NULL,
 original_stored_crc INTEGER,
 original_calculated_crc INTEGER
);
CREATE INDEX relationships_target ON relationships(target_identity);
PRAGMA user_version = 3;
