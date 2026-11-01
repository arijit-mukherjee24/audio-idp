import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace
from audio_idp.services.review import link_manual

class BatchFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Store(self.temp.name);self.w=Workspace(self.s)
        self.batch=self.w.batch('Persistent batch')
        self.w.upload(self.batch,'sample.wav',b'audio','English')
        self.r=self.s.list('recording',batch=self.batch)[0]
        self.s.save('transcript',{'text':'My printer is broken','language':'en','segments':[]},id='tr-'+self.r['id'],parent=self.r['id'],batch=self.batch)
    def tearDown(self):
        self.w.jobs.audio.shutdown(wait=True);self.w.jobs.cloud.shutdown(wait=True);self.temp.cleanup()
    def wait(self):
        deadline=time.monotonic()+10
        while any(not f.done() for f in self.w.jobs.futures):
            if time.monotonic()>deadline:self.fail('Job timeout')
            time.sleep(.01)

    def test_single_accepted_suggestion_is_assigned_without_second_guessing(self):
        c=self.w.definition('class','Support','Product help',True)
        link_manual(self.s,self.r['id'],c)
        with patch('audio_idp.workflow.coordinator.classify') as model:
            self.w.classify_batch(self.batch,force=True);self.wait()
            model.assert_not_called()
        result=self.s.get('cl-'+self.r['id'])['data']
        self.assertEqual(result['class_id'],c)
        self.assertEqual(result['source'],'accepted_suggestion')

    def test_inflight_model_cannot_overwrite_manual_class_or_confirmation(self):
        self.w.definition('class','Support','Product help',True)
        ready,release=threading.Event(),threading.Event()
        def model(*args):
            ready.set();release.wait(5)
            return {'class':'Unclassified','reason':'Old response'}
        with patch('audio_idp.workflow.coordinator.client'),patch('audio_idp.workflow.coordinator.classify',side_effect=model):
            self.w.classify_batch(self.batch)
            self.assertTrue(ready.wait(2))
            c=self.w.manual_class(self.r['id'],'Repair Request','Requests to repair existing equipment')
            release.set();self.wait()
        self.assertEqual(self.s.get('cl-'+self.r['id'])['data']['class_id'],c)
        self.assertEqual(self.s.jobs()[0]['status'],'cancelled')
        with patch('audio_idp.workflow.coordinator.classify') as model:
            self.w.classify_batch(self.batch,force=True);self.wait();model.assert_not_called()
        self.assertEqual(self.s.get('cl-'+self.r['id'])['data']['class_id'],c)

    def test_multiple_candidates_use_model_and_ignore_unrelated_schema_revisions(self):
        ids=[]
        for name in ['Support','Repairs']:
            c=self.w.definition('class',name,name+' requests',True);ids.append(c);link_manual(self.s,self.r['id'],c)
        unrelated=self.w.definition('class','Sales','Purchase requests',True)
        ready,release=threading.Event(),threading.Event()
        def model(client,model,text,classes):
            self.assertEqual({c['name'] for c in classes},{'Support','Repairs'})
            ready.set();release.wait(5)
            return {'class':'Repairs','reason':'Repair explicitly requested'}
        with patch('audio_idp.workflow.coordinator.client'),patch('audio_idp.workflow.coordinator.classify',side_effect=model):
            self.w.classify_batch(self.batch)
            self.assertTrue(ready.wait(2))
            self.w.definition('field','issue','Problem reported',False,parent=ids[0])
            release.set();self.wait()
        self.assertEqual(self.s.get('cl-'+self.r['id'])['data']['class_id'],ids[1])

    def test_json_tracks_full_batch_jobs_edits_and_deletion(self):
        c=self.w.manual_class(self.r['id'],'Support','Product help')
        f=self.w.definition('field','issue','Reported issue',True,parent=c)
        self.s.save('extraction',{'fields':{'issue':{'value':'Broken printer','evidence':'printer is broken'}}},id='ex-'+self.r['id'],parent=self.r['id'],batch=self.batch)
        with self.s.connection() as db:
            for i in range(125):
                db.execute('INSERT INTO jobs(id,kind,target,batch,status,created,updated) VALUES(?,?,?,?,?,?,?)',(str(i),'test',self.r['id'],self.batch,'completed',time.time(),time.time()))
        path=self.w.snapshots.path(self.batch)
        document=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(document['batch']['name'],'Persistent batch')
        self.assertEqual(document['recordings'][0]['classification']['class_name'],'Support')
        self.assertEqual(document['recordings'][0]['extraction']['fields']['issue']['value'],'Broken printer')
        self.assertEqual(len(document['jobs']),125)
        self.assertEqual(len(self.s.jobs(self.batch,limit=25,offset=100)),25)
        self.s.delete(f)
        document=json.loads(path.read_text(encoding='utf-8'))
        self.assertFalse(document['classes'][0]['fields'])
        self.s.delete(self.batch)
        self.assertFalse(path.exists())

    def test_master_reset_removes_json_snapshots(self):
        path=self.w.snapshots.path(self.batch)
        self.assertTrue(path.exists())
        self.s.reset()
        self.assertFalse(list(self.w.snapshots.folder.glob('*.json')))

    def test_retry_unclassified_model_result_uses_accepted_suggestion(self):
        c=self.w.definition('class','Support','Product help',True)
        self.w.assign(self.r['id'],None,'Previous AI mismatch',source='model')
        link_manual(self.s,self.r['id'],c)
        self.w.classify_batch(self.batch);self.wait()
        self.assertEqual(self.s.get('cl-'+self.r['id'])['data']['class_id'],c)

    def test_json_failure_preserves_sqlite_and_is_retryable(self):
        with patch('audio_idp.services.batch_snapshots.os.replace',side_effect=OSError('Test file busy')):
            b=self.s.get(self.batch)
            self.s.save('batch',dict(b['data'],name='Updated name'),id=self.batch)
            self.assertTrue(self.w.snapshots.error)
            self.assertEqual(self.s.get(self.batch)['data']['name'],'Updated name')
        self.w.snapshots.sync()
        self.assertFalse(self.w.snapshots.error)
        self.assertEqual(json.loads(self.w.snapshots.path(self.batch).read_text())['batch']['name'],'Updated name')
