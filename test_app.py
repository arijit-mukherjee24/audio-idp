"""List/detail UI tests: selection, isolation and approval transitions."""
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace
from audio_idp.services.review import link_manual

class AppWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.w=Workspace(Store(self.temp.name))
        self.batch=self.w.batch('Review batch')
        self.ids=[];self.classes=[]
        for i,(name,text,class_name,field) in enumerate([
            ('alpha.wav','Alpha needs printer repairs.','Support','issue'),
            ('beta.wav','Beta has a purchase budget.','Sales','budget')]):
            self.w.upload(self.batch,name,bytes([i]),'English')
            r=self.w.store.list('recording',batch=self.batch)[-1]
            self.ids.append(r['id'])
            self.w.store.save('transcript',{'text':text,'language':'en','segments':[]},id='tr-'+r['id'],parent=r['id'],batch=self.batch)
            c=self.w.definition('class',class_name,class_name+' conversations',True)
            self.classes.append(c)
            link_manual(self.w.store,r['id'],c)
            self.w.definition('field',field,'Extract '+field,True,parent=c)
            self.w.assign(r['id'],c)
            self.w.store.save('extraction',{'fields':{field:{'value':'Alpha value' if i==0 else 'Beta value','evidence':text}}},id='ex-'+r['id'],parent=r['id'],batch=self.batch)
        self.patch=patch('audio_idp.ui.session.workspace',return_value=self.w)
        self.patch.start()
        self.advance=patch.object(self.w,'advance')
        self.advance.start()

    def tearDown(self):
        self.advance.stop();self.patch.stop()
        self.w.jobs.audio.shutdown(wait=True);self.w.jobs.cloud.shutdown(wait=True)
        self.temp.cleanup()

    def app(self,stage):
        b=self.w.store.get(self.batch)
        self.w.store.save('batch',dict(b['data'],guided_stage=stage,flow_version=3),id=self.batch)
        app=AppTest.from_file('app.py',default_timeout=20).run()
        next(b for b in app.button if b.key=='open-batch-'+self.batch).click().run()
        self.assertFalse(app.exception,str(app.exception))
        return app

    def choose(self,app,id):
        next(r for r in app.radio if r.label=='Files').set_value(id).run()
        self.assertFalse(app.exception,str(app.exception))

    def test_upload_defaults_first_and_displays_only_selected_transcript(self):
        app=self.app(0)
        self.assertEqual(next(r for r in app.radio if r.label=='Files').value,self.ids[0])
        self.assertEqual([t.value for t in app.text_area],['Alpha needs printer repairs.'])
        self.choose(app,self.ids[1])
        self.assertEqual([t.value for t in app.text_area],['Beta has a purchase budget.'])
        self.w.upload(self.batch,'pending.wav',b'pending','English')
        pending=self.w.store.list('recording',batch=self.batch)[-1]
        app.run();self.choose(app,pending['id'])
        self.assertFalse(app.text_area)
        self.assertTrue(any('will appear' in i.value for i in app.info))
        self.w.store.save('transcript',{'text':'Gamma transcription','language':'en','segments':[]},id='tr-'+pending['id'],parent=pending['id'],batch=self.batch)
        app.run()
        self.assertEqual(next(r for r in app.radio if r.label=='Files').value,pending['id'])
        self.assertEqual([t.value for t in app.text_area],['Gamma transcription'])

    def test_selected_file_has_its_own_class_suggestion(self):
        app=self.app(1)
        self.assertEqual(next(t for t in app.text_input if t.label=='Class name').value,'Support')
        self.choose(app,self.ids[1])
        self.assertEqual(next(t for t in app.text_input if t.label=='Class name').value,'Sales')
        self.assertEqual(next(t for t in app.text_area if t.label=='Class description').value,'Sales conversations')

    def test_refresh_targets_only_selected_file_and_manual_existing_assignment(self):
        app=self.app(1)
        self.choose(app,self.ids[1])
        with patch.object(self.w,'suggest_file') as suggest:
            next(b for b in app.button if b.label=='Refresh suggestion for this file').click().run()
            suggest.assert_called_once_with(self.ids[1],refresh=True)
        next(s for s in app.selectbox if s.label=='Choose an existing class').set_value(self.classes[0])
        next(b for b in app.button if b.label=='Assign selected class').click().run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertEqual(self.w.store.get('cl-'+self.ids[1])['data']['class_id'],self.classes[0])

    def test_field_and_result_details_follow_selected_file(self):
        app=self.app(2)
        self.assertEqual(next(t for t in app.text_input if t.label=='Field name').value,'issue')
        self.choose(app,self.ids[1])
        self.assertEqual(next(t for t in app.text_input if t.label=='Field name').value,'budget')
        app=self.app(3)
        self.assertIn('Alpha value',app.dataframe[0].value.to_json())
        self.assertNotIn('Beta value',app.dataframe[0].value.to_json())
        self.choose(app,self.ids[1])
        self.assertIn('Beta value',app.dataframe[0].value.to_json())
        self.assertNotIn('Alpha value',app.dataframe[0].value.to_json())

    def test_approval_flow_and_utilities_render(self):
        app=self.app(1)
        next(b for b in app.button if b.label=='Continue to field suggestions →').click().run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertNotIn('Classification',[m.value for m in app.markdown])
        with patch.object(self.w,'extract_batch') as extract:
            next(b for b in app.button if b.label=='Extract accepted fields →').click().run()
            self.assertFalse(app.exception,str(app.exception))
            extract.assert_called_once_with(self.batch)
        next(r for r in app.radio if r.label=='Workspace').set_value('Batch jobs').run()
        self.assertFalse(app.exception,str(app.exception))
        next(b for b in app.button if b.label=='← Back to dashboard').click().run()
        for view in ['Settings','Dashboard']:
            next(r for r in app.radio if r.label=='Workspace').set_value(view).run()
            self.assertFalse(app.exception,str(app.exception))

    def test_dashboard_is_home_and_create_new_batch_opens_empty_flow(self):
        app=AppTest.from_file('app.py',default_timeout=20).run()
        self.assertIn('Your audio workspace.',[t.value for t in app.title])
        self.assertIn('Saved batches',[s.value for s in app.subheader])
        self.assertFalse(app.dataframe)
        self.assertEqual(next(r for r in app.radio if r.label=='Workspace').options,['Dashboard','Settings'])
        next(b for b in app.button if b.label=='Create new batch').click().run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertIn('Listen to one conversation at a time.',[t.value for t in app.title])
        self.assertIsNone(app.session_state['batch'])
        self.assertEqual(next(r for r in app.radio if r.label=='Workspace').options,['Pipeline'])
        next(b for b in app.button if b.label=='← Back to dashboard').click().run()
        self.assertIn('Your audio workspace.',[t.value for t in app.title])

    def test_manual_class_is_available_for_unclassified_file(self):
        self.w.store.delete('cl-'+self.ids[0])
        app=self.app(2)
        next(t for t in app.text_input if t.label=='New class name').set_value('Manual repair')
        next(t for t in app.text_area if t.label=='New class description').set_value('Requests for equipment repair')
        next(b for b in app.button if b.label=='Create & assign class').click().run()
        self.assertFalse(app.exception,str(app.exception))
        a=self.w.store.get('cl-'+self.ids[0])
        self.assertEqual(self.w.store.get(a['data']['class_id'])['data']['name'],'Manual repair')
        self.assertEqual(a['data']['source'],'manual')

    def test_manual_class_creation_when_no_suggestions_exist(self):
        for id in self.classes:self.w.store.delete(id)
        app=self.app(1)
        next(t for t in app.text_input if t.label=='New class name').set_value('New category')
        next(t for t in app.text_area if t.label=='New class description').set_value('A manually defined category')
        next(b for b in app.button if b.label=='Create & assign class').click().run()
        self.assertFalse(app.exception,str(app.exception))
        a=self.w.store.get('cl-'+self.ids[0])
        self.assertEqual(self.w.store.get(a['data']['class_id'])['data']['name'],'New category')

    def test_batch_job_history_is_paginated_and_scoped_to_opened_batch(self):
        import time
        with self.w.store.connection() as db:
            for i in range(125):
                db.execute('INSERT INTO jobs(id,kind,target,batch,status,created,updated) VALUES(?,?,?,?,?,?,?)',
                    (str(i),'example',self.ids[0],self.batch,'completed',i,time.time()))
        other=self.w.batch('Other batch')
        with self.w.store.connection() as db:
            db.execute('INSERT INTO jobs(id,kind,target,batch,status,created,updated) VALUES(?,?,?,?,?,?,?)',
                ('other-job','unrelated','unrelated',other,'failed',0,time.time()))
        app=AppTest.from_file('app.py',default_timeout=20).run()
        self.assertFalse(app.dataframe)
        next(b for b in app.button if b.key=='open-batch-'+self.batch).click().run()
        self.assertEqual(app.session_state['batch'],self.batch)
        next(r for r in app.radio if r.label=='Workspace').set_value('Batch jobs').run()
        self.assertIn('Batch jobs',[t.value for t in app.title])
        next(n for n in app.number_input if n.label=='Job page').set_value(5).run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertEqual(len(app.dataframe[0].value),25)
        self.assertTrue(any('125 jobs · Page 5 of 5' in c.value for c in app.caption))

        self.assertNotIn('unrelated',app.dataframe[0].value.to_json())
        next(s for s in app.selectbox if s.label=='Job status').set_value('failed').run()
        self.assertFalse(app.dataframe)
        next(b for b in app.button if b.label=='← Back to batch').click().run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertEqual(self.w.store.get(self.batch)['data'].get('guided_stage',0),0)
        next(b for b in app.button if b.label=='← Back to dashboard').click().run()
        self.assertFalse(app.dataframe)
        next(b for b in app.button if b.label=='Create new batch').click().run()
        self.assertNotIn('Batch jobs',next(r for r in app.radio if r.label=='Workspace').options)
