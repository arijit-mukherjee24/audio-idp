import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace
from audio_idp.domain.validation import suggestions

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.s=Store(self.temp.name)
        self.w=Workspace(self.s)
        self.batch=self.w.batch('Test batch')

    def tearDown(self):
        self.w.jobs.audio.shutdown(wait=True)
        self.w.jobs.cloud.shutdown(wait=True)
        self.temp.cleanup()

    def wait(self):
        deadline=time.monotonic()+10
        while any(not f.done() for f in self.w.jobs.futures):
            if time.monotonic()>deadline: self.fail('Jobs timed out')
            time.sleep(.01)

    def recording(self,name='one.wav',content=b'one'):
        self.w.upload(self.batch,name,content,'English')
        return next(r for r in self.s.list('recording',batch=self.batch) if r['data']['name']==name)

    def transcript(self,r):
        return self.s.save('transcript',{'text':'My printer is broken.', 'segments':[], 'language':'en'},id='tr-'+r['id'],parent=r['id'],batch=self.batch)

    def test_parallel_transcription_and_partial_failure(self):
        self.recording()
        self.recording('two.wav',b'two')
        barrier=threading.Barrier(2)
        release=threading.Event()
        def transcribe(r):
            barrier.wait(timeout=3)
            release.wait(3)
            if r['data']['name']=='two.wav': raise ValueError('Invalid audio')
            return {'text':'Hello','language':'en','segments':[]}
        with patch.object(self.w,'_transcribe',side_effect=transcribe):
            self.w.transcribe_batch(self.batch)
            self.w.transcribe_batch(self.batch)
            release.set()
            self.wait()
        self.assertEqual(len(self.w.transcripts(self.batch)),1)
        self.assertEqual(sorted(j['status'] for j in self.s.jobs()),['completed','failed'])

    def test_approval_classification_shared_fields_and_extraction(self):
        records=[self.recording(),self.recording('two.wav',b'two')]
        for r in records:self.transcript(r)
        c=self.w.definition('class','Support','Product support',True)
        f=self.w.definition('field','issue','Reported issue',True,parent=c)
        self.w.definition('field','sentiment','Customer sentiment',False,parent=c)
        with patch('audio_idp.workflow.coordinator.client'),patch('audio_idp.workflow.coordinator.classify',return_value={'class':'Support','reason':'Broken product'}):
            self.w.classify_batch(self.batch)
            self.wait()
        self.assertEqual(len(self.s.list('classification')),2)
        def extract(client,model,text,fields):
            self.assertEqual([x['name'] for x in fields],['issue'])
            return {'issue':{'value':'Broken printer','evidence':'My printer is broken.'}}
        with patch('audio_idp.workflow.coordinator.client'),patch('audio_idp.workflow.coordinator.extract',side_effect=extract):
            self.w.extract_batch(self.batch)
            self.wait()
        self.assertEqual(len(self.s.list('extraction')),2)
        self.assertTrue(self.s.search('printer',kind='extraction'))
        self.s.delete(c)
        self.assertFalse(self.s.list('field'))
        self.assertFalse(self.s.list('classification'))
        self.assertFalse(self.s.list('extraction'))
        self.assertEqual(len(self.w.transcripts(self.batch)),2)

    def test_delete_and_reset_discard_late_results(self):
        r=self.recording()
        ready,release=threading.Event(),threading.Event()
        def work():
            ready.set(); release.wait(5)
            return {'text':'Should never reappear'}
        self.w.jobs.submit('transcribe',r['id'],self.batch,[r],work,lambda data:self.s.save('transcript',data,parent=r['id'],batch=self.batch))
        ready.wait(2)
        self.s.reset()
        release.set();self.wait()
        self.assertFalse(self.s.list())
        self.assertFalse(self.s.search('reappear'))
        self.assertFalse(list(self.s.uploads.iterdir()))

    def test_persistence_search_delete_and_class_boundaries(self):
        r=self.recording();self.transcript(r)
        self.w.definition('class','A'*80,'D'*400,True)
        with self.assertRaises(ValueError):self.w.definition('class','A'*81,'description',True)
        with self.assertRaises(ValueError):self.w.definition('class','x','D'*401,True)
        self.assertTrue(Store(self.temp.name).search('printer'))
        self.s.delete(r['id'])
        self.assertFalse(self.s.search('printer'))
        self.assertFalse(list(self.s.uploads.iterdir()))

    def test_field_suggestion_limit(self):
        fields=[{'name':str(i),'description':'Description'} for i in range(10)]
        self.assertEqual(len(suggestions({'fields':fields},'fields')),10)
        with self.assertRaises(ValueError):suggestions({'fields':fields+ [{'name':'11','description':'Extra'}]},'fields')

    def test_suggestions_approval_and_deletion_end_to_end(self):
        r=self.recording();self.transcript(r)
        with patch('audio_idp.workflow.coordinator.suggest_classes',return_value=[{'name':'Support','description':'Product help'}]):
            self.w.suggest_classes(self.batch);self.wait()
        c=self.w.classes(False)[0]
        self.assertFalse(self.w.classes())
        self.w.definition('class','Support','Product help',True,id=c['id'])
        self.w.assign(r['id'],c['id'])
        with patch('audio_idp.workflow.coordinator.suggest_fields',return_value=[{'name':'issue','description':'Reported problem'},{'name':'customer','description':'Caller name'}]):
            self.w.suggest_fields(c['id'],self.batch);self.wait()
        self.assertEqual(len(self.w.fields(c['id'],False)),2)
        self.assertFalse(self.w.fields(c['id']))
        f=self.w.fields(c['id'],False)[0]
        self.w.definition('field',f['data']['name'],f['data']['description'],True,id=f['id'],parent=c['id'])
        self.assertEqual(len(self.w.fields(c['id'])),1)
        self.s.save('extraction',{'fields':{'issue':{'value':'Paper jam','evidence':'printer'},'customer':{'value':None,'evidence':None}}},id='ex-'+r['id'],parent=r['id'],batch=self.batch)
        self.s.delete(f['id'])
        self.assertEqual(list(self.s.get('ex-'+r['id'])['data']['fields']),['customer'])
        self.s.delete(self.batch)
        self.assertEqual(len(self.w.classes()),1)
        self.assertFalse(self.s.list('recording'))
        self.assertFalse(self.s.search('printer'))

    def test_edit_invalidates_and_stale_job_is_discarded(self):
        r=self.recording();id=self.transcript(r)
        original=self.s.get(id)
        ready,release=threading.Event(),threading.Event()
        def work():ready.set();release.wait(5);return {}
        self.w.jobs.submit('extract',r['id'],self.batch,[original],work,lambda data:self.s.save('extraction',data,parent=r['id']))
        ready.wait(2)
        self.w.edit_transcript(original,'Changed transcript')
        release.set();self.wait()
        self.assertFalse(self.s.list('extraction'))

    def test_automatic_suggestion_assigns_then_discovers_fields(self):
        self.w.jobs.on_complete=self.w.advance
        r=self.recording()
        with patch.object(self.w,'_transcribe',return_value={'text':'My printer is broken.','language':'en','segments':[]}), patch('audio_idp.workflow.coordinator.suggest_file_class',return_value={'class':{'name':'Support','description':'Product help'},'reason':'Repair request'}),patch('audio_idp.workflow.coordinator.suggest_fields',return_value=[{'name':'issue','description':'Reported issue'}]):
            self.w.transcribe_batch(self.batch);self.wait()
        c=self.w.classes()[0]
        self.assertEqual(self.s.get('cl-'+r['id'])['data']['class_id'],c['id'])
        self.assertEqual(len(self.w.fields(c['id'],False)),1)
        self.assertFalse(self.s.list('extraction'))
        self.assertFalse(any(j['kind']=='classify' for j in self.s.jobs()))

    def test_merge_preserves_recordings_and_shared_fields(self):
        r=self.recording();self.transcript(r)
        source=self.w.definition('class','Help','Requests for help',True)
        target=self.w.definition('class','Support','Product help',True)
        self.w.definition('field','issue','Reported issue',True,parent=source)
        self.w.assign(r['id'],source)
        self.w.merge(source,target)
        self.assertIsNone(self.s.get(source))
        self.assertEqual(self.s.get('cl-'+r['id'])['data']['class_id'],target)
        self.assertEqual(len(self.w.fields(target)),1)

    def test_classification_uses_only_classes_selected_for_batch(self):
        r=self.recording();self.transcript(r)
        selected=self.w.definition('class','Support','Product help',True)
        self.w.definition('class','Sales','Purchase inquiries',True)
        b=self.s.get(self.batch)
        self.s.save('batch',dict(b['data'],class_ids=[selected]),id=self.batch)
        with patch('audio_idp.workflow.coordinator.client'),patch('audio_idp.workflow.coordinator.classify',return_value={'class':'Support','reason':'Product help'}) as classify:
            self.w.classify_batch(self.batch);self.wait()
            self.assertEqual([c['name'] for c in classify.call_args.args[3]],['Support'])

    def test_all_class_field_jobs_overlap_with_independent_sources_and_progress(self):
        from audio_idp.ui.field_progress import snapshot
        for i in range(4):
            r=self.recording(f'record-{i}.wav',f'audio-{i}'.encode())
            t=self.transcript(r)
            self.s.save('transcript',dict(self.s.get(t)['data'],text=f'Record {i} issue'),id=t)
            c=self.w.definition('class',f'Class {i}',f'Purpose {i}',True)
            self.w.assign(r['id'],c)
        started=threading.Barrier(4)
        release=threading.Event()
        seen=[]
        def suggest(c,transcripts,existing):
            i=int(c['name'].split()[-1])
            self.assertEqual(transcripts,[f'Record {i} issue'])
            seen.append(i)
            if i<3:
                started.wait(timeout=5)
                release.wait(5)
            if i==1: raise ValueError('Synthetic failure')
            return [{'name':f'field_{i}','description':f'Fact from record {i}'}]
        with patch('audio_idp.workflow.coordinator.suggest_fields',side_effect=suggest):
            try:
                self.w.suggest_fields_batch(self.batch)
                started.wait(timeout=5)
                statuses=snapshot(self.w,self.batch)
                self.assertEqual(sum(s['state']=='running' for s in statuses),3)
                self.assertEqual(sum(s['state']=='queued' for s in statuses),1)
                self.w.suggest_fields_batch(self.batch)
                self.assertEqual(len(self.s.jobs()),4)
            finally: release.set()
            self.wait()
        statuses=snapshot(self.w,self.batch)
        self.assertEqual(sum(s['state']=='completed' for s in statuses),3)
        self.assertEqual(sum(s['state']=='failed' for s in statuses),1)
        self.assertEqual(sorted(seen),[0,1,2,3])
        self.assertEqual(len(self.s.list('field')),3)

    def test_new_transcript_during_discovery_gets_independent_assignment(self):
        self.w.jobs.on_complete=self.w.advance
        r=self.recording();self.transcript(r)
        ready,release=threading.Event(),threading.Event()
        calls=[]
        def suggest(text,existing):
            calls.append(text)
            if len(calls)==1:ready.set();release.wait(5)
            return {'class':{'name':'Support','description':'Product help'},'reason':'Repair request'}
        with patch('audio_idp.workflow.coordinator.suggest_file_class',side_effect=suggest),patch('audio_idp.workflow.coordinator.suggest_fields',return_value=[]):
            self.w.advance(self.batch)
            self.assertTrue(ready.wait(2))
            second=self.recording('two.wav',b'two');self.transcript(second)
            self.w.advance(self.batch)
            release.set();self.wait()
        self.assertEqual(len(calls),2)
        self.assertEqual(len(self.w.classes()),1)
        self.assertEqual(len(self.s.list('classification')),2)
        self.assertEqual(len([j for j in self.s.jobs() if j['kind']=='suggest class']),2)

if __name__=='__main__':unittest.main()
