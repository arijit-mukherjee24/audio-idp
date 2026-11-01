"""SQLite workspace with transactional full-text indexing and revision checks."""
from __future__ import annotations
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from audio_idp.domain.models import Entity, Job

class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.uploads = self.folder / 'uploads'
        self.uploads.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.resetting = False
        self.on_change = None
        with self.connection() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 4:
                raise ValueError('Workspace was created by a newer application version.')
            if version == 0:
                schema = Path(__file__).with_name('migrations') / '001_initial.sql'
                db.executescript(schema.read_text(encoding='utf-8'))
                version=1
            if version==1:
                schema=Path(__file__).with_name('migrations') / '002_batch_snapshots.sql'
                db.executescript(schema.read_text(encoding='utf-8'))
                version=2
            if version==2:
                schema=Path(__file__).with_name('migrations') / '003_snapshot_trigger_upserts.sql'
                db.executescript(schema.read_text(encoding='utf-8'))
                version=3
            if version==3:
                schema=Path(__file__).with_name('migrations') / '004_converse_cache.sql'
                db.executescript(schema.read_text(encoding='utf-8'))
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("UPDATE jobs SET status='interrupted',error='Application restarted. Retry this stage.' WHERE status IN ('queued','running')")

    @contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.folder / 'audio-idp.sqlite3', timeout=15)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            changed=False
            try:
                yield db
                db.commit()
                changed=db.total_changes>0
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
            if changed and self.on_change:
                self.on_change()

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        row = dict(row)
        row['data'] = json.loads(row['data'])
        return row

    def get(self, id) -> Entity | None:
        with self.connection() as db:
            return self.unpack(db.execute('SELECT * FROM entities WHERE id=?', (id,)).fetchone())

    def list(self, kind=None, batch=None, parent=None) -> list[Entity]:
        clauses, args = [], []
        for key, value in [('kind', kind), ('batch', batch), ('parent', parent)]:
            if value is not None:
                clauses.append(key + '=?')
                args.append(value)
        sql = 'SELECT * FROM entities' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY updated'
        with self.connection() as db:
            return [self.unpack(r) for r in db.execute(sql, args)]

    def save(self, kind, data, *, id=None, parent=None, batch=None):
        with self.lock:
            if self.resetting:
                raise ValueError('Workspace reset in progress.')
            entity_id = id or uuid.uuid4().hex
            old = self.get(entity_id)
            with self.connection() as db:
                db.execute('''INSERT INTO entities(id,kind,parent,batch,data,updated) VALUES(?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET data=excluded.data, revision=entities.revision+1,updated=excluded.updated''',
                           (entity_id, kind, parent, batch, json.dumps(data, ensure_ascii=False), time.time()))
            # Every schema edit also changes the class revision used by active jobs.
            if kind == 'field':
                owner = parent or (old and old['parent'])
                with self.connection() as db:
                    db.execute('UPDATE entities SET revision=revision+1 WHERE id=?', (owner,))
                self.invalidate_class(owner, fields_only=True)
            return entity_id

    def invalidate_class(self, class_id, fields_only=False):
        for assignment in self.list('classification'):
            if assignment['data'].get('class_id') == class_id:
                with self.connection() as db:
                    db.execute("DELETE FROM entities WHERE kind='extraction' AND parent=?", (assignment['parent'],))
                    if not fields_only:
                        db.execute('DELETE FROM entities WHERE id=?', (assignment['id'],))

    def delete(self, id):
        with self.lock:
            item = self.get(id)
            if not item:
                return
            with self.connection() as db:
                db.execute('DELETE FROM request_cache WHERE key IN (SELECT key FROM request_cache_owners WHERE target=? OR batch=?)',(id,id))
            if item['kind'] in ('class','recording'):
                for b in self.list('batch'):
                    data=dict(b['data'])
                    choices=data.get('file_class_choices',{})
                    data['file_class_choices']={key:value for key,value in choices.items()
                        if not (item['kind']=='recording' and key==id) and not (item['kind']=='class' and value['class_id']==id)}
                    if item['kind']=='class' and 'class_ids' in data:data['class_ids']=[key for key in data['class_ids'] if key!=id]
                    if data!=b['data']:self.save('batch',data,id=b['id'])
            if item['kind'] == 'class':
                self.invalidate_class(id)
            if item['kind'] == 'field':
                with self.connection() as db:
                    db.execute('UPDATE entities SET revision=revision+1 WHERE id=?', (item['parent'],))
                for assignment in self.list('classification'):
                    if assignment['data'].get('class_id') == item['parent']:
                        result = self.get('ex-'+assignment['parent'])
                        if result:
                            values = dict(result['data']['fields'])
                            values.pop(item['data']['name'], None)
                            self.save('extraction', {'fields': values}, id=result['id'])
            if item['kind'] in ('transcript', 'classification'):
                with self.connection() as db:
                    db.execute("DELETE FROM entities WHERE parent=? AND kind IN ('classification','extraction') AND id<>?", (item['parent'], id))
            paths = [r['data']['path'] for r in self.list('recording') if r['id'] == id or r['batch'] == id]
            # Audio cleanup is attempted first. On failure, retain DB references for retry.
            for path in paths:
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(self.uploads.resolve()):
                    raise ValueError('Refusing to remove a file outside workspace uploads.')
                resolved.unlink(missing_ok=True)
            with self.connection() as db:
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE (target=? OR batch=?) AND status IN ('queued','running')", (time.time(), id, id))
                db.execute('DELETE FROM entities WHERE id=?', (id,))
                db.execute('DELETE FROM jobs WHERE batch=? OR target=?', (id, id))

    def search(self, query, kind=None, batch=None, offset=0):
        words = query.strip().split()[:12]
        if not words:
            return []
        expression = ' AND '.join('"' + word.replace('"', '""') + '"*' for word in words)
        sql = '''SELECT e.* FROM search_index s JOIN entities e ON e.id=s.id
                 WHERE search_index MATCH ?'''
        args = [expression]
        if kind:
            sql += ' AND e.kind=?'
            args.append(kind)
        if batch:
            sql += ' AND e.batch=?'
            args.append(batch)
        sql += ' ORDER BY rank LIMIT 20 OFFSET ?'
        args.append(offset)
        with self.connection() as db:
            return [self.unpack(row) for row in db.execute(sql, args)]

    def jobs(self, batch=None, *, limit=None, offset=0, status=None) -> list[Job]:
        with self.connection() as db:
            sql, args = 'SELECT * FROM jobs', []
            if batch:
                sql += ' WHERE batch=?'
                args.append(batch)
            if status:
                sql+=(' AND ' if batch else ' WHERE ')+'status=?'
                args.append(status)
            sql+=' ORDER BY created DESC'
            if limit is not None:
                sql+=' LIMIT ? OFFSET ?';args.extend([int(limit),int(offset)])
            return [dict(r) for r in db.execute(sql,args)]

    def job_status(self, id, status, error=''):
        with self.connection() as db:
            db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE id=?', (status, error, time.time(), id))

    def reset(self, remove_models=False):
        from audio_idp.providers.whisper import whisper_model
        from audio_idp.config import MODEL_CACHE
        import shutil
        with self.lock:
            self.resetting = True
            try:
                with self.connection() as db:
                    db.execute("UPDATE jobs SET status='cancelled'")
                # Delete only the explicitly owned data directories after checking paths.
                uploads = self.uploads.resolve()
                if uploads.parent != self.folder.resolve() or uploads.name != 'uploads':
                    raise ValueError('Invalid upload directory.')
                for file in uploads.iterdir():
                    if file.is_file():
                        file.unlink()
                if remove_models:
                    whisper_model.cache_clear()
                    if MODEL_CACHE.resolve().parent != Path(__file__).resolve().parents[2]:
                        raise ValueError('Invalid model cache directory.')
                    if MODEL_CACHE.exists():
                        shutil.rmtree(MODEL_CACHE)
                with self.connection() as db:
                    db.execute('DELETE FROM request_cache')
                    db.execute('UPDATE cache_state SET generation=generation+1 WHERE id=1')
                    db.execute('DELETE FROM entities')
                    db.execute('DELETE FROM search_index')
                    db.execute('DELETE FROM jobs')
            finally:
                self.resetting = False
