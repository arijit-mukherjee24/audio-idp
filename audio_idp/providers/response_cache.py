"""Workspace-scoped exact-response cache; validated jobs commit pending responses."""
import copy
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

_context=ContextVar('converse_cache_context',default=None)

def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()

class ResponseCache:
    def __init__(self,store):
        self.store=store
        self.locks={}
        self.mutex=threading.Lock()
    def key_lock(self,key):
        with self.mutex:return self.locks.setdefault(key,threading.RLock())
    def generation(self):
        with self.store.connection() as db:return db.execute('SELECT generation FROM cache_state WHERE id=1').fetchone()[0]
    def get(self,key):
        with self.store.connection() as db:
            row=db.execute('SELECT response FROM request_cache WHERE key=?',(key,)).fetchone()
            if not row:return None
            try:
                value=json.loads(row[0])
                if not isinstance(value,dict):raise ValueError('Invalid cached response')
            except (ValueError,TypeError):
                db.execute('DELETE FROM request_cache WHERE key=?',(key,));return None
            db.execute('UPDATE request_cache SET hits=hits+1 WHERE key=?',(key,))
            return value
    def clear(self):
        with self.store.connection() as db:
            db.execute('DELETE FROM request_cache')
            db.execute('UPDATE cache_state SET generation=generation+1 WHERE id=1')
    def stats(self):
        with self.store.connection() as db:
            row=db.execute('SELECT count(*),coalesce(sum(hits),0) FROM request_cache').fetchone()
            return {'entries':row[0],'hits':row[1]}

class CallContext:
    def __init__(self,cache,bypass,owners):
        self.cache,self.bypass,self.owners=cache,bypass,owners
        self.generation=cache.generation()
        self.pending={};self.keys=[];self.hits=0;self.held={}
    def fetch(self,key,invoke):
        if key not in self.held:
            lock=self.cache.key_lock(key);lock.acquire();self.held[key]=lock
        if key not in self.keys:self.keys.append(key)
        if key in self.pending:return copy.deepcopy(self.pending[key])
        value=None if self.bypass else self.cache.get(key)
        if value is not None:
            self.hits+=1;return copy.deepcopy(value)
        value=invoke()
        self.pending[key]=copy.deepcopy(value)
        return value
    def commit(self):
        with self.cache.store.connection() as db:
            if db.execute('SELECT generation FROM cache_state WHERE id=1').fetchone()[0]!=self.generation:return
            for key,response in self.pending.items():
                db.execute('INSERT INTO request_cache(key,response,created) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET response=excluded.response,created=excluded.created',
                           (key,json.dumps(response,ensure_ascii=False),time.time()))
            for key in self.keys:
                for batch,target in self.owners:
                    db.execute('INSERT OR IGNORE INTO request_cache_owners(key,batch,target) SELECT ?,?,? WHERE EXISTS(SELECT 1 FROM entities WHERE id=? AND kind=\'batch\') AND EXISTS(SELECT 1 FROM request_cache WHERE key=?)',
                               (key,batch,target,batch,key))
    def close(self):
        for lock in reversed(list(self.held.values())):lock.release()

@contextmanager
def cache_scope(cache,*,bypass=False,owners=()):
    context=CallContext(cache,bypass,owners)
    token=_context.set(context)
    try:yield context
    finally:
        _context.reset(token);context.close()

def reuse_or_call(payload,invoke):
    context=_context.get()
    return context.fetch(fingerprint(payload),invoke) if context else invoke()
