PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS entities (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent TEXT REFERENCES entities(id) ON DELETE CASCADE,
              batch TEXT REFERENCES entities(id) ON DELETE CASCADE, data TEXT NOT NULL,
              revision INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS entities_kind ON entities(kind, batch, parent);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, kind TEXT, target TEXT, batch TEXT, status TEXT,
              error TEXT DEFAULT '', created REAL, updated REAL);
            CREATE INDEX IF NOT EXISTS job_status ON jobs(status, target);
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(id UNINDEXED, text, tokenize='unicode61');
            CREATE TRIGGER IF NOT EXISTS entity_insert AFTER INSERT ON entities BEGIN
              INSERT INTO search_index(id,text) VALUES(new.id,new.data); END;
            CREATE TRIGGER IF NOT EXISTS entity_update AFTER UPDATE ON entities BEGIN
              DELETE FROM search_index WHERE id=old.id;
              INSERT INTO search_index(id,text) VALUES(new.id,new.data); END;
            CREATE TRIGGER IF NOT EXISTS entity_delete AFTER DELETE ON entities BEGIN
              DELETE FROM search_index WHERE id=old.id; END;
            PRAGMA user_version=1;
