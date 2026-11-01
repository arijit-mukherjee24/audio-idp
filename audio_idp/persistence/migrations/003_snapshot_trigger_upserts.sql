-- Avoid trigger conflict policies being overridden by an outer entity UPSERT.
DROP TRIGGER IF EXISTS snapshot_entity_insert;
DROP TRIGGER IF EXISTS snapshot_entity_update;
DROP TRIGGER IF EXISTS snapshot_entity_delete;
DROP TRIGGER IF EXISTS snapshot_job_insert;
DROP TRIGGER IF EXISTS snapshot_job_update;
DROP TRIGGER IF EXISTS snapshot_job_delete;
CREATE TRIGGER snapshot_entity_insert AFTER INSERT ON entities BEGIN
  INSERT INTO snapshot_dirty(batch)
  SELECT batch FROM (
    SELECT new.id AS batch WHERE new.kind='batch'
    UNION SELECT new.batch WHERE new.batch IS NOT NULL
    UNION SELECT id FROM entities WHERE kind='batch' AND new.kind IN ('class','field')
  ) AS targets WHERE NOT EXISTS(SELECT 1 FROM snapshot_dirty WHERE snapshot_dirty.batch=targets.batch);
END;
CREATE TRIGGER snapshot_entity_update AFTER UPDATE ON entities BEGIN
  INSERT INTO snapshot_dirty(batch)
  SELECT batch FROM (
    SELECT new.id AS batch WHERE new.kind='batch'
    UNION SELECT new.batch WHERE new.batch IS NOT NULL
    UNION SELECT old.batch WHERE old.batch IS NOT NULL
    UNION SELECT id FROM entities WHERE kind='batch' AND new.kind IN ('class','field')
  ) AS targets WHERE NOT EXISTS(SELECT 1 FROM snapshot_dirty WHERE snapshot_dirty.batch=targets.batch);
END;
CREATE TRIGGER snapshot_entity_delete AFTER DELETE ON entities BEGIN
  INSERT INTO snapshot_dirty(batch)
  SELECT batch FROM (
    SELECT old.id AS batch WHERE old.kind='batch'
    UNION SELECT old.batch WHERE old.batch IS NOT NULL
    UNION SELECT id FROM entities WHERE kind='batch' AND old.kind IN ('class','field')
  ) AS targets WHERE NOT EXISTS(SELECT 1 FROM snapshot_dirty WHERE snapshot_dirty.batch=targets.batch);
END;
CREATE TRIGGER snapshot_job_insert AFTER INSERT ON jobs BEGIN
  INSERT INTO snapshot_dirty SELECT new.batch WHERE new.batch IS NOT NULL AND NOT EXISTS(SELECT 1 FROM snapshot_dirty WHERE batch=new.batch);
END;
CREATE TRIGGER snapshot_job_update AFTER UPDATE ON jobs BEGIN
  INSERT INTO snapshot_dirty SELECT new.batch WHERE new.batch IS NOT NULL AND NOT EXISTS(SELECT 1 FROM snapshot_dirty WHERE batch=new.batch);
END;
CREATE TRIGGER snapshot_job_delete AFTER DELETE ON jobs BEGIN
  INSERT INTO snapshot_dirty SELECT old.batch WHERE old.batch IS NOT NULL AND NOT EXISTS(SELECT 1 FROM snapshot_dirty WHERE batch=old.batch);
END;
PRAGMA user_version=3;
