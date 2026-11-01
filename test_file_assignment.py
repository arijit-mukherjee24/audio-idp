import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace
from audio_idp.services.file_class_suggestion import suggest_file_class

class FileAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.w=Workspace(Store(self.temp.name));self.s=self.w.store
        self.batch=self.w.batch('Batch');self.ids=[]
        for i in range(2):
            self.w.upload(self.batch,f'{i}.wav',str(i).encode(),'English')
            id=self.s.list('recording',batch=self.batch)[-1]['id'];self.ids.append(id)
            self.s.save('transcript',{'text':f'File {i} repair request'},id='tr-'+id,parent=id,batch=self.batch)
        self.proposal={'class':{'name':'Support','description':'Repair requests'},'reason':'Product repair'}
    def tearDown(self):
        self.w.jobs.audio.shutdown(wait=True);self.w.jobs.cloud.shutdown(wait=True);self.temp.cleanup()
    def wait(self):
        deadline=time.monotonic()+8
        while any(not f.done() for f in self.w.jobs.futures):
            if time.monotonic()>deadline:self.fail('Jobs timed out')
            time.sleep(.01)
    def test_suggestion_assigns_shared_class_without_classify(self):
        with patch('audio_idp.workflow.coordinator.suggest_file_class',return_value=self.proposal):
            for id in self.ids:self.w.suggest_file(id)
            self.wait()
        assignments=self.s.list('classification')
        self.assertEqual(len(assignments),2)
        self.assertEqual(len({a['data']['class_id'] for a in assignments}),1)
        self.assertEqual(len(self.w.classes()),1)
        self.assertTrue(all(a['data']['source']=='ai_suggestion' for a in assignments))
        self.assertFalse(any(j['kind']=='classify' for j in self.s.jobs()))
    def test_refresh_is_file_specific_and_manual_change_wins(self):
        for id in self.ids:self.w.manual_class(id,'Custom '+id,'User category')
        second=self.s.get('cl-'+self.ids[1])
        with patch('audio_idp.workflow.coordinator.suggest_file_class',return_value=self.proposal) as suggest:
            self.w.suggest_file(self.ids[0],refresh=True);self.wait()
            self.assertEqual(suggest.call_count,1)
        self.assertEqual(self.s.get('cl-'+self.ids[1]),second)
        self.assertEqual(self.s.get(self.s.get('cl-'+self.ids[0])['data']['class_id'])['data']['name'],'Support')
        ready,release=threading.Event(),threading.Event()
        def delayed(*args):ready.set();release.wait(3);return self.proposal
        with patch('audio_idp.workflow.coordinator.suggest_file_class',side_effect=delayed):
            self.w.suggest_file(self.ids[0],refresh=True);self.assertTrue(ready.wait(2))
            custom=self.w.manual_class(self.ids[0],'Override','Manual override')
            release.set();self.wait()
        self.assertEqual(self.s.get('cl-'+self.ids[0])['data']['class_id'],custom)
    def test_failed_refresh_preserves_assignment_and_empty_suggestion_is_reviewable(self):
        custom=self.w.manual_class(self.ids[0],'Custom','User category')
        with patch('audio_idp.workflow.coordinator.suggest_file_class',side_effect=ValueError('Network issue')):
            self.w.suggest_file(self.ids[0],refresh=True);self.wait()
        self.assertEqual(self.s.get('cl-'+self.ids[0])['data']['class_id'],custom)
        with patch('audio_idp.workflow.coordinator.suggest_file_class',return_value={'class':None,'reason':'Insufficient content'}):
            self.w.suggest_file(self.ids[0],refresh=True);self.wait()
        self.assertIsNone(self.s.get('cl-'+self.ids[0])['data']['class_id'])
    def test_service_validates_limits_reuses_existing_and_omits_recording_ids(self):
        with patch('audio_idp.services.file_class_suggestion.request',return_value=self.proposal) as request:
            result=suggest_file_class('Repair request',[{'name':'Support','description':'Canonical description'}])
            self.assertEqual(result['class']['description'],'Canonical description')
            self.assertEqual(set(request.call_args.args[1]),{'transcript','existing_classes'})
        for invalid in ({'class':{'name':None,'description':'desc'},'reason':'x'}, {'class':{'name':'a'*81,'description':'desc'},'reason':'x'}):
            with patch('audio_idp.services.file_class_suggestion.request',return_value=invalid):
                with self.assertRaises(ValueError):suggest_file_class('text',[])

    def test_shared_fields_are_rescheduled_when_membership_changes_mid_request(self):
        c=self.w.manual_class(self.ids[0],'Support','Repair requests')
        self.w.jobs.on_complete=self.w.advance
        ready,release=threading.Event(),threading.Event();sizes=[]
        def suggest(class_data,texts,fields):
            sizes.append(len(texts))
            if len(sizes)==1:ready.set();release.wait(3)
            return [{'name':'issue','description':'Reported issue'}]
        with patch('audio_idp.workflow.coordinator.suggest_fields',side_effect=suggest):
            self.w.suggest_fields(c,self.batch);self.assertTrue(ready.wait(2))
            self.w.confirm_class(self.ids[1],c)
            self.w.advance(self.batch)
            release.set();self.wait()
        self.assertEqual(sizes,[1,2])
        self.assertEqual(len(self.w.fields(c,False)),1)
        jobs=[j for j in self.s.jobs() if j['kind']=='suggest fields']
        self.assertEqual(sorted(j['status'] for j in jobs),['cancelled','completed'])
