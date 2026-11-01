import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from audio_idp.config import TRANSCRIPTION_WORKERS
from audio_idp.providers.response_cache import ResponseCache, cache_scope

def safe_error(exc):
    if hasattr(exc, 'response'):
        code = exc.response.get('Error', {}).get('Code', 'ClientError')
        if code in ('ExpiredTokenException','ExpiredToken','UnrecognizedClientException','InvalidClientTokenId'):
            return f'{code}: AWS credentials are expired or invalid. Refresh your local default profile and retry.'
        return f'{code}: verify Bedrock model access, permissions, region and request limits, then retry.'
    if isinstance(exc, ValueError):
        return str(exc)[:500]
    name = type(exc).__name__
    if name == 'ProfileNotFound':
        return 'AWS default profile cannot be read. Start the application from your normal PowerShell session.'
    if name in ('NoCredentialsError', 'UnauthorizedSSOTokenError', 'TokenRetrievalError'):
        return 'AWS credentials are missing or expired. Refresh your local AWS login and retry.'
    if name == 'ModelDownloadError':
        return str(exc)
    return f'{name}: check local installation, AWS access, or network, then retry.'

class JobManager:
    def __init__(self, store):
        self.store = store
        self.cache = ResponseCache(store)
        self.audio = ThreadPoolExecutor(TRANSCRIPTION_WORKERS, thread_name_prefix='audio')
        self.cloud = ThreadPoolExecutor(3, thread_name_prefix='bedrock')
        self.futures = set()
        self.on_complete = None

    def submit(self, kind, target, batch, dependencies, work, commit, guard=lambda: True, refresh=False, cache_owners=()):
        s = self.store
        with s.lock:
            if s.resetting:
                return False
            if any(j['kind'] == kind and j['target'] == target and j['status'] in ('queued','running') for j in s.jobs()):
                return False
            id = uuid.uuid4().hex
            with s.connection() as db:
                db.execute("UPDATE jobs SET status='superseded' WHERE kind=? AND target=? AND status IN ('failed','interrupted')", (kind,target))
                db.execute('INSERT INTO jobs(id,kind,target,batch,status,created,updated) VALUES(?,?,?,?,?,?,?)',
                           (id,kind,target,batch,'queued',time.time(),time.time()))
            deps = [(d['id'], d['revision']) for d in dependencies]
            owners={(batch,target),*cache_owners}
            for d in dependencies:
                owners.add((d.get('batch') or batch,d['id']))
                if d['kind']=='transcript':owners.add((d.get('batch') or batch,d['parent']))

        def valid():
            with s.connection() as db:
                job = db.execute('SELECT status FROM jobs WHERE id=?', (id,)).fetchone()
            return job and job['status'] in ('queued','running') and guard() and all(
                (current := s.get(key)) and current['revision'] == version for key, version in deps)

        def cancel_stale():
            with s.connection() as db:
                db.execute("UPDATE jobs SET status='cancelled',error='Inputs changed; result discarded.',updated=? WHERE id=? AND status IN ('queued','running')",(time.time(),id))

        def execute():
            try:
                with s.lock:
                    if not valid():
                        cancel_stale()
                        return
                    s.job_status(id, 'running')
                with cache_scope(self.cache,bypass=refresh,owners=owners) as context:
                    value = work()
                    with s.lock:
                        if valid():
                            commit(value)
                            # Include outputs (e.g. the automatically assigned class) in deletion ownership.
                            assignment=s.get('cl-'+target)
                            if assignment and assignment['data'].get('class_id'):
                                context.owners.add((batch,assignment['data']['class_id']))
                            context.commit()
                            with s.connection() as db:
                                db.execute('UPDATE jobs SET cache_hit=?,request_hash=? WHERE id=?',
                                           (int(context.hits>0),context.keys[-1] if context.keys else None,id))
                            s.job_status(id, 'completed')
                        else:
                            cancel_stale()
            except Exception as exc:
                with s.lock:
                    if valid():
                        s.job_status(id, 'failed', safe_error(exc))
                    else:
                        cancel_stale()
            finally:
                if self.on_complete:
                    try:
                        self.on_complete(batch)
                    except Exception:
                        # Processing errors are persisted on the stage's own job.
                        pass
        future = (self.audio if kind == 'transcribe' else self.cloud).submit(execute)
        with s.lock:
            self.futures.add(future)
            self.futures = {f for f in self.futures if not f.done()}
        return True
