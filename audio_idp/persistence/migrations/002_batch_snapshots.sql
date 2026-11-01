CREATE TABLE IF NOT EXISTS snapshot_dirty(batch TEXT PRIMARY KEY);
CREATE TRIGGER IF NOT EXISTS snapshot_entity_insert AFTER INSERT ON entities BEGIN
  INSERT OR IGNORE INTO snapshot_dirty SELECT CASE WHEN new.kind='batch' THEN new.id ELSE new.batch END WHERE new.kind='batch' OR new.batch IS NOT NULL;
  INSERT OR IGNORE INTO snapshot_dirty SELECT id FROM entities WHERE kind='batch' AND new.kind IN ('class','field');
END;
CREATE TRIGGER IF NOT EXISTS snapshot_entity_update AFTER UPDATE ON entities BEGIN
  INSERT OR IGNORE INTO snapshot_dirty SELECT CASE WHEN new.kind='batch' THEN new.id ELSE new.batch END WHERE new.kind='batch' OR new.batch IS NOT NULL;
  INSERT OR IGNORE INTO snapshot_dirty SELECT old.batch WHERE old.batch IS NOT NULL;
  INSERT OR IGNORE INTO snapshot_dirty SELECT id FROM entities WHERE kind='batch' AND new.kind IN ('class','field');
END;
CREATE TRIGGER IF NOT EXISTS snapshot_entity_delete AFTER DELETE ON entities BEGIN
  INSERT OR IGNORE INTO snapshot_dirty SELECT CASE WHEN old.kind='batch' THEN old.id ELSE old.batch END WHERE old.kind='batch' OR old.batch IS NOT NULL;
  INSERT OR IGNORE INTO snapshot_dirty SELECT id FROM entities WHERE kind='batch' AND old.kind IN ('class','field');
END;
CREATE TRIGGER IF NOT EXISTS snapshot_job_insert AFTER INSERT ON jobs BEGIN
  INSERT OR IGNORE INTO snapshot_dirty SELECT new.batch WHERE new.batch IS NOT NULL;
END;
CREATE TRIGGER IF NOT EXISTS snapshot_job_update AFTER UPDATE ON jobs BEGIN
  INSERT OR IGNORE INTO snapshot_dirty SELECT new.batch WHERE new.batch IS NOT NULL;
END;
CREATE TRIGGER IF NOT EXISTS snapshot_job_delete AFTER DELETE ON jobs BEGIN
  INSERT OR IGNORE INTO snapshot_dirty SELECT old.batch WHERE old.batch IS NOT NULL;
END;
INSERT OR IGNORE INTO snapshot_dirty SELECT id FROM entities WHERE kind='batch';
PRAGMA user_version=2;
