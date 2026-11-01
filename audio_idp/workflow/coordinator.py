import hashlib
import json
import uuid
from functools import wraps
from pathlib import Path
from audio_idp.domain.validation import definition
from audio_idp.providers.bedrock import client
from audio_idp.config import MODEL
from audio_idp.services.transcription import transcribe, MAX_BYTES, FORMATS, LANGUAGES
from audio_idp.services.classification import classify
from audio_idp.services.extraction import extract
from audio_idp.services.class_suggestion import suggest_classes
from audio_idp.services.file_class_suggestion import suggest_file_class
from audio_idp.services.field_suggestion import suggest_fields
from audio_idp.services.export import export_csv
from audio_idp.workflow.job_manager import JobManager
from audio_idp.services.assignment import semantic_class, assignment_token, choice
from audio_idp.services.review import candidates, link_manual
from audio_idp.services.batch_snapshots import BatchSnapshots

def serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.store.lock:
            return method(self, *args, **kwargs)
    return run

class Workspace:
    def __init__(self, store, automatic=False):
        self.store = store
        self.jobs = JobManager(store)
        self.snapshots=BatchSnapshots(store)
        if automatic:
            self.jobs.on_complete = self.advance

    def batch(self, name):
        if not name.strip():
            raise ValueError('Enter a batch name.')
        return self.store.save('batch', {'name': name.strip()})

    def upload(self, batch, name, content, language):
        if Path(name).suffix.lower().lstrip('.') not in FORMATS or len(content) > MAX_BYTES:
            raise ValueError('Choose a supported audio file no larger than 50 MB.')
        if not content:
            raise ValueError('The audio file is empty.')
        s = self.store
        with s.lock:
            existing = s.list('recording', batch=batch)
            digest = hashlib.sha256(content).hexdigest()
            if any(r['data']['hash'] == digest for r in existing):
                return
            if len(existing) >= 10:
                raise ValueError('A batch supports up to 10 recordings.')
            id = uuid.uuid4().hex
            path = s.uploads / (id + Path(name).suffix.lower())
            path.write_bytes(content)
            try:
                s.save('recording', {'name': Path(name).name, 'path': str(path), 'hash': digest,
                                    'language': language}, id=id, batch=batch)
            except Exception:
                path.unlink(missing_ok=True)
                raise

    def transcripts(self, batch):
        return self.store.list('transcript', batch=batch)

    def classes(self, accepted=True):
        return [c for c in self.store.list('class') if c['data']['accepted'] == accepted]

    def fields(self, class_id, accepted=True):
        return [f for f in self.store.list('field', parent=class_id) if f['data']['accepted'] == accepted]

    def definition(self, kind, name, description, accepted, *, id=None, parent=None, batch=None):
        s = self.store
        data = definition(name, description, is_class=kind == 'class')
        with s.lock:
            if any(x['id'] != id and x['data']['name'].casefold() == data['name'].casefold()
                   for x in s.list(kind, parent=parent)):
                raise ValueError('That name already exists. Merge or choose another name.')
            old = s.get(id) if id else None
            if old:
                data = dict(old['data'], **data)
            data['accepted'] = accepted
            if kind == 'class' and old and data != old['data']:
                s.invalidate_class(id)
                data.pop('field_stamp',None)
            result = s.save(kind, data, id=id, parent=parent, batch=batch)
            if kind == 'class' and accepted:
                with s.connection() as db:
                    db.execute('UPDATE entities SET batch=NULL WHERE id=?', (result,))
            return result

    @serialized
    def transcribe_batch(self, batch):
        s = self.store
        for r in s.list('recording', batch=batch):
            if s.get('tr-' + r['id']):
                continue
            self.jobs.submit('transcribe', r['id'], batch, [r],
                lambda r=r: self._transcribe(r),
                lambda value, r=r: s.save('transcript', value, id='tr-'+r['id'], parent=r['id'], batch=batch))

    @staticmethod
    def _transcribe(recording):
        data = recording['data']
        result = transcribe(Path(data['path']), LANGUAGES.get(data['language']), speakers=False)
        if result['language'] not in LANGUAGES.values():
            raise ValueError('Detected language is outside English, Spanish and French. Change the recording language.')
        return result

    def edit_transcript(self, transcript, text):
        if not text.strip():
            raise ValueError('Transcript cannot be empty.')
        s = self.store
        with s.lock:
            s.delete('cl-' + transcript['parent'])
            s.delete('ex-' + transcript['parent'])
            s.save('transcript', dict(transcript['data'], text=text, edited=True), id=transcript['id'])

    def suggest_classes(self, batch):
        s = self.store
        transcripts = self.transcripts(batch)
        if not transcripts:
            raise ValueError('Transcribe at least one recording first.')
        deps = transcripts + s.list('class')
        def commit(rows):
            existing = {c['data']['name'].casefold():c for c in s.list('class')}
            input_ids={t['parent'] for t in transcripts}
            revisions={t['parent']:t['revision'] for t in transcripts}
            # Remove obsolete associations for this batch before installing fresh ones.
            for c in existing.values():
                old_sources=c['data'].get('sources',[])
                if c['data'].get('mapped') and any(id in input_ids for id in old_sources):
                    manual=set(c['data'].get('manual_sources',[]))
                    data=dict(c['data'],sources=[id for id in old_sources if id not in input_ids or id in manual],
                              source_revisions={id:rev for id,rev in c['data'].get('source_revisions',{}).items() if id not in input_ids or id in manual})
                    s.save('class',data,id=c['id'])
            for row in rows:
                key=row['name'].casefold()
                sources=row.get('source_ids',[])
                prior=s.get(existing[key]['id']) if key in existing else None
                data=dict(prior['data'] if prior else {},name=row['name'],description=row['description'],
                          accepted=prior['data']['accepted'] if prior else False,
                          sources=list(dict.fromkeys((prior['data'].get('sources',[]) if prior else [])+sources)),
                          mapped=bool(sources),source_revisions=dict(prior['data'].get('source_revisions',{}) if prior else {},**{id:revisions[id] for id in sources if id in revisions}))
                id=s.save('class',data,id=prior['id'] if prior else None,batch=None if prior and prior['data']['accepted'] else batch)
                existing[key]=s.get(id)
        signature=[(t['id'],t['revision']) for t in transcripts]
        return self.jobs.submit('suggest classes', batch, batch, deps,
            lambda: suggest_classes([{'id':t['parent'], 'text':t['data']['text']} for t in transcripts],
                                    [c['data'] for c in self.classes()]), commit,
            guard=lambda:[(t['id'],t['revision']) for t in self.transcripts(batch)]==signature)

    @serialized
    def suggest_file(self,recording,refresh=False):
        s=self.store
        r=s.get(recording);t=s.get('tr-'+recording)
        if not r or not t:raise ValueError('Complete transcription before suggesting a class.')
        batch=r['batch']
        existing=self.classes()
        catalog=[dict(c['data']) for c in existing]
        semantics=[semantic_class(c) for c in existing]
        token=assignment_token(s,recording)
        def commit(result):
            # Only this file's associations and assignment are replaced.
            for c in s.list('class'):
                if recording not in c['data'].get('sources',[]):continue
                data=dict(c['data'],sources=[id for id in c['data'].get('sources',[]) if id!=recording],
                          manual_sources=[id for id in c['data'].get('manual_sources',[]) if id!=recording],
                          source_revisions={id:rev for id,rev in c['data'].get('source_revisions',{}).items() if id!=recording})
                s.save('class',data,id=c['id'])
            b=s.get(batch)
            choices=dict(b['data'].get('file_class_choices',{}));choices.pop(recording,None)
            s.save('batch',dict(b['data'],file_class_choices=choices),id=batch)
            row=result['class']
            class_id=None
            if row:
                c=next((c for c in s.list('class') if c['data']['name'].casefold()==row['name'].casefold()),None)
                if not c:
                    class_id=self.definition('class',row['name'],row['description'],True)
                    c=s.get(class_id)
                elif not c['data']['accepted']:
                    self.definition('class',c['data']['name'],c['data']['description'],True,id=c['id'])
                    c=s.get(c['id'])
                class_id=c['id']
                s.save('class',dict(c['data'],mapped=True,sources=list(dict.fromkeys(c['data'].get('sources',[])+[recording])),
                       source_revisions=dict(c['data'].get('source_revisions',{}),**{recording:t['revision']})),id=class_id)
            self.assign(recording,class_id,result['reason'],source='ai_suggestion')
        submitted=self.jobs.submit('suggest class',recording,batch,[t],
            lambda:suggest_file_class(t['data']['text'],catalog),commit,
            guard=lambda:assignment_token(s,recording)==token and all(
                (current:=s.get(item[0])) and semantic_class(current)==item for item in semantics),refresh=refresh,
            cache_owners={(batch,c['id']) for c in existing})
        if submitted:
            b=s.get(batch);stamps=dict(b['data'].get('file_suggestion_stamps',{}))
            stamps[recording]=[t['revision'],1]
            s.save('batch',dict(b['data'],file_suggestion_stamps=stamps),id=batch)
        return submitted

    def classification_catalog(self, batch):
        selected = self.store.get(batch)['data'].get('class_ids')
        return [c for c in self.classes() if selected is None or c['id'] in selected]

    @serialized
    def confirm_class(self,recording,class_id,source='user_confirmed'):
        s=self.store
        r=s.get(recording);t=s.get('tr-'+recording);c=s.get(class_id)
        if not r or not t or not c:raise ValueError('Choose a class and a successfully transcribed file.')
        if not c['data']['accepted']:
            self.definition('class',c['data']['name'],c['data']['description'],True,id=class_id)
            c=s.get(class_id)
        link_manual(s,recording,class_id)
        b=s.get(r['batch'])
        choices=dict(b['data'].get('file_class_choices',{}))
        choices[recording]={'class_id':class_id,'transcript_revision':t['revision'],
                            'definition':[c['data']['name'],c['data']['description']]}
        selected=b['data'].get('class_ids')
        ids=list(dict.fromkeys((selected if selected is not None else [c['id'] for c in self.classes()])+[class_id]))
        s.save('batch',dict(b['data'],class_ids=ids,file_class_choices=choices),id=b['id'])
        self.assign(recording,class_id,'Explicitly selected by the user.',source=source)

    @serialized
    def manual_class(self,recording,name,description):
        r=self.store.get(recording)
        if not r or not self.store.get('tr-'+recording):raise ValueError('Complete transcription before assigning a class.')
        id=self.definition('class',name,description,True)
        self.confirm_class(recording,id,source='manual')
        return id

    @serialized
    def classify_batch(self, batch, force=False):
        s = self.store
        classes = self.classification_catalog(batch)
        if not classes:
            raise ValueError('Accept or create at least one class first.')
        for t in self.transcripts(batch):
            confirmed=choice(s,t['parent'])
            prior=s.get('cl-'+t['parent'])
            if confirmed:
                if not prior or prior['data']['class_id']!=confirmed['id']:
                    self.assign(t['parent'],confirmed['id'],'Explicitly selected by the user.',source='user_confirmed')
                continue
            if prior and prior['data'].get('source') in ('manual','user_confirmed') and prior['data'].get('transcript_revision')==t['revision']:
                continue
            if not force and prior and prior['data']['class_id']:
                continue
            if force:
                s.delete('cl-'+t['parent'])
                s.delete('ex-'+t['parent'])
            mapped=[c for c in candidates(s,t['parent']) if c['data']['accepted'] and c['id'] in {x['id'] for x in classes}]
            options=mapped or classes
            definitions=[dict(c['data'],fields=[]) for c in options]
            semantics=[semantic_class(c) for c in options]
            token=assignment_token(s,t['parent'])
            def guard(t=t,semantics=semantics,token=token):
                return (s.get(batch) is not None and assignment_token(s,t['parent'])==token
                        and all(item[0] in {c['id'] for c in self.classification_catalog(batch)}
                                and (current:=s.get(item[0])) and semantic_class(current)==item for item in semantics))
            if len(mapped)==1:
                work=lambda c=mapped[0]:{'class':c['data']['name'],'reason':'Assigned from the single accepted class suggested for this transcript.','source':'accepted_suggestion'}
            else:
                def work(t=t,definitions=definitions):
                    result=classify(client,MODEL,t['data']['text'],definitions)
                    return dict(result,source='model')
            self.jobs.submit('classify',t['parent'],batch,[t],work,
                lambda result,t=t,options=options:self.assign(t['parent'],next((c['id'] for c in options if c['data']['name']==result['class']),None),result['reason'],source=result['source']),guard=guard)

    def assign(self, recording, class_id, reason='Manually assigned',source='manual'):
        s = self.store
        r = s.get(recording)
        if not r:
            raise ValueError('Recording was deleted.')
        with s.lock:
            if class_id:
                c = s.get(class_id)
                if not c or not c['data']['accepted']:
                    raise ValueError('Choose an accepted class.')
            old = s.get('cl-'+recording)
            s.delete('ex-'+recording)
            t=s.get('tr-'+recording)
            if source=='manual':
                b=s.get(r['batch'])
                choices=dict(b['data'].get('file_class_choices',{}))
                if class_id and t:
                    c=s.get(class_id)
                    choices[recording]={'class_id':class_id,'transcript_revision':t['revision'],
                                        'definition':[c['data']['name'],c['data']['description']]}
                else:choices.pop(recording,None)
                ids=b['data'].get('class_ids')
                if class_id:ids=list(dict.fromkeys((ids if ids is not None else [c['id'] for c in self.classes()])+[class_id]))
                if choices!=b['data'].get('file_class_choices',{}) or ids!=b['data'].get('class_ids'):
                    data=dict(b['data'],file_class_choices=choices)
                    if ids is not None:data['class_ids']=ids
                    s.save('batch',data,id=b['id'])
            s.save('classification', {'class_id':class_id,'reason':reason,'source':source,
                    'transcript_revision':t['revision'] if t else None}, id='cl-'+recording, parent=recording, batch=r['batch'])

    @serialized
    def suggest_fields(self, class_id, batch, refresh=False):
        s = self.store
        c = s.get(class_id)
        if not c or not c['data']['accepted']:
            raise ValueError('Accept this class first.')
        assignments = [a for a in s.list('classification') if a['data']['class_id']==class_id]
        transcripts = [s.get('tr-'+a['parent']) for a in assignments]
        transcripts = [t for t in transcripts if t]
        if not transcripts:
            raise ValueError('Classify at least one recording into this class first.')
        fields = s.list('field', parent=class_id)
        membership = [(a['id'],a['revision']) for a in assignments]
        def commit(rows):
            # Replace draft suggestions only; preserve accepted definitions.
            for f in self.fields(class_id, False):
                s.delete(f['id'])
            existing = {f['data']['name'].casefold() for f in self.fields(class_id)}
            for row in rows:
                if row['name'].casefold() not in existing:
                    s.save('field', dict(row, accepted=False), parent=class_id)
                    existing.add(row['name'].casefold())
        return self.jobs.submit('suggest fields', class_id, batch, [c]+transcripts+assignments+fields,
            lambda: suggest_fields(c['data'], [t['data']['text'] for t in transcripts], [f['data'] for f in fields if f['data']['accepted']]), commit,
            guard=lambda: [(a['id'],a['revision']) for a in s.list('classification') if a['data']['class_id']==class_id]==membership,refresh=refresh)

    @serialized
    def suggest_fields_batch(self, batch, force=False):
        """Queue all class requests before workers begin; each uses its own transcripts."""
        ids = {a['data']['class_id'] for a in self.store.list('classification',batch=batch)} - {None}
        for c in self.classes():
            if c['id'] not in ids:
                continue
            job = next((j for j in self.store.jobs() if j['kind']=='suggest fields' and j['target']==c['id']),None)
            if force or not job or job['status'] in ('failed','interrupted','cancelled'):
                self.suggest_fields(c['id'],batch,refresh=force)

    @serialized
    def extract_batch(self, batch, force=False):
        s = self.store
        count = 0
        for t in self.transcripts(batch):
            a = s.get('cl-'+t['parent'])
            c = s.get(a['data']['class_id']) if a and a['data']['class_id'] else None
            fields = self.fields(c['id']) if c else []
            if not fields:
                continue
            count += 1
            if not force and s.get('ex-'+t['parent']):
                continue
            self.jobs.submit('extract', t['parent'], batch, [t,a,c]+fields,
                lambda t=t, fields=fields: extract(client, MODEL, t['data']['text'], [f['data'] for f in fields]),
                lambda result, t=t: s.save('extraction', {'fields':result}, id='ex-'+t['parent'], parent=t['parent'], batch=batch))
        if not count:
            raise ValueError('Accept fields for at least one assigned class first. Unclassified recordings are skipped.')

    def merge(self, source, target):
        s = self.store
        if source == target:
            raise ValueError('Choose a different destination class.')
        destination = s.get(target)
        if not destination or not destination['data']['accepted']:
            raise ValueError('Merge into an accepted class.')
        with s.lock:
            for a in s.list('classification'):
                if a['data']['class_id'] == source:
                    self.assign(a['parent'], target)
            for f in s.list('field', parent=source):
                if not any(x['data']['name'].casefold()==f['data']['name'].casefold() for x in s.list('field', parent=target)):
                    s.save('field', f['data'], parent=target)
            s.delete(source)

    def export(self, batch):
        s = self.store
        output = []
        for r in s.list('recording', batch=batch):
            t, a, e = (s.get(prefix+r['id']) for prefix in ('tr-', 'cl-', 'ex-'))
            c = s.get(a['data']['class_id']) if a and a['data']['class_id'] else None
            output.append({'name': r['data']['name'], 'transcript':t['data'] if t else None,
                           'class':c['data']['name'] if c else 'Unclassified', **(e['data'] if e else {})})
        return json.dumps(output, ensure_ascii=False, indent=2), export_csv(output)

    @serialized
    def advance(self, batch):
        """Persisted stamps make automatic suggestion scheduling idempotent across reruns."""
        s = self.store
        b = s.get(batch)
        if not b:
            return
        transcripts = self.transcripts(batch)
        for t in transcripts:
            a=s.get('cl-'+t['parent'])
            c=s.get(a['data']['class_id']) if a and a['data']['class_id'] else None
            # Keep existing/manual assignments; new transcripts get one suggestion each.
            if c and a['data'].get('transcript_revision',t['revision'])==t['revision']:continue
            b=s.get(batch)
            if b['data'].get('file_suggestion_stamps',{}).get(t['parent']) != [t['revision'],1]:
                self.suggest_file(t['parent'])
        for c in self.classes():
            assignments = [a for a in s.list('classification') if a['data']['class_id']==c['id']]
            if not any(a['batch']==batch for a in assignments):
                continue
            if any(j['kind']=='suggest fields' and j['target']==c['id'] and j['status'] in ('queued','running') for j in s.jobs()):
                continue
            field_stamp = json.dumps([(a['id'],a['revision'], (s.get('tr-'+a['parent']) or {}).get('revision')) for a in assignments])
            job=next((j for j in s.jobs() if j['kind']=='suggest fields' and j['target']==c['id']),None)
            if c['data'].get('field_stamp') != field_stamp or (job and job['status']=='cancelled' and job['error'].startswith('Inputs changed')):
                s.save('class',dict(c['data'],field_stamp=field_stamp),id=c['id'])
                self.suggest_fields(c['id'],batch)
