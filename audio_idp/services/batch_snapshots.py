"""Atomic, automatically maintained JSON snapshots of each SQLite batch."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from audio_idp.services.review import batch_candidates

class BatchSnapshots:
    def __init__(self,store):
        self.store=store
        self.folder=store.folder/'batches'
        self.syncing=False
        self.error=''
        try:self.folder.mkdir(exist_ok=True)
        except OSError:self.error='JSON snapshot directory is unavailable. SQLite data is preserved.'
        with store.connection() as db:
            db.execute("INSERT OR IGNORE INTO snapshot_dirty SELECT id FROM entities WHERE kind='batch'")
        store.on_change=self.sync
        self.sync()

    def path(self,batch):
        if not batch or any(c not in '0123456789abcdef' for c in batch):raise ValueError('Invalid batch identifier.')
        return self.folder/(batch+'.json')

    def document(self,batch):
        s=self.store
        with s.lock:
            b=s.get(batch)
            if not b:return None
            recordings=[]
            classes={c['id']:c for c in batch_candidates(s,batch)+s.list('class',batch=batch)}
            for r in s.list('recording',batch=batch):
                t=s.get('tr-'+r['id']);a=s.get('cl-'+r['id']);e=s.get('ex-'+r['id'])
                c=s.get(a['data']['class_id']) if a and a['data']['class_id'] else None
                if c:classes[c['id']]=c
                recordings.append({'id':r['id'],**r['data'],'transcript':t['data'] if t else None,
                    'classification':dict(a['data'],class_name=c['data']['name'] if c else 'Unclassified') if a else None,
                    'extraction':e['data'] if e else None})
            definitions=[{'id':c['id'],**c['data'],'fields':[{'id':f['id'],**f['data']} for f in s.list('field',parent=c['id'])]} for c in classes.values()]
            return {'schema_version':1,'saved_at':datetime.now(timezone.utc).isoformat(),
                    'batch':{'id':b['id'],**b['data']},'recordings':recordings,'classes':definitions,'jobs':s.jobs(batch)}

    def sync(self):
        s=self.store
        with s.lock:
            if self.syncing:return
            self.syncing=True
            try:
                self.folder.mkdir(exist_ok=True)
                with s.connection() as db:dirty=[r[0] for r in db.execute('SELECT batch FROM snapshot_dirty')]
                for batch in dirty:
                    path=self.path(batch)
                    document=self.document(batch)
                    if document is None:path.unlink(missing_ok=True)
                    else:
                        temporary=path.with_suffix('.json.tmp')
                        try:
                            temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
                            os.replace(temporary,path)
                        finally:temporary.unlink(missing_ok=True)
                    with s.connection() as db:db.execute('DELETE FROM snapshot_dirty WHERE batch=?',(batch,))
                self.error=''
            except (OSError,ValueError) as exc:
                # SQLite has committed. Retain dirty IDs so retry can repair the JSON copy.
                self.error=f'JSON snapshot could not be saved ({type(exc).__name__}). SQLite data is preserved.'
            finally:self.syncing=False
