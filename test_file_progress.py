import tempfile
import time
import unittest
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace
from audio_idp.ui.file_progress import snapshot

class FileProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.w=Workspace(Store(self.temp.name))
        self.s=self.w.store
        self.batch=self.w.batch('File status test')
        self.ids=[]
        for i in range(3):
            self.w.upload(self.batch,f'file-{i}.wav',str(i).encode(),'English')
            self.ids.append(self.s.list('recording',batch=self.batch)[-1]['id'])
        for id in self.ids[:2]:
            self.s.save('transcript',{'text':'Printer broken','language':'en','segments':[]},id='tr-'+id,parent=id,batch=self.batch)

    def tearDown(self):
        self.w.jobs.audio.shutdown(wait=True)
        self.w.jobs.cloud.shutdown(wait=True)
        self.temp.cleanup()

    def job(self,id,kind,target,status,error=''):
        with self.s.connection() as db:
            db.execute('INSERT INTO jobs(id,kind,target,batch,status,error,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (id,kind,target,self.batch,status,error,time.time(),time.time()))

    def test_upload_transcription_and_shared_discovery_are_independent(self):
        self.job('bad','transcribe',self.ids[2],'failed','Audio could not be decoded')
        self.job('classes','suggest classes',self.batch,'running')
        rows=snapshot(self.w,self.batch)
        self.assertEqual([r['Upload'] for r in rows],['Saved']*3)
        self.assertEqual([r['Transcription'] for r in rows],['Complete','Complete','Failed'])
        self.assertTrue(rows[0]['Class suggestions'].startswith('Running'))
        self.assertTrue(rows[1]['Class suggestions'].startswith('Running'))
        self.assertEqual(rows[2]['Class suggestions'],'Waiting for transcript')
        self.assertIn('decoded',rows[2]['Details'])
        self.assertNotIn('decoded',rows[0]['Details'])

    def test_shared_field_job_projects_to_each_file_but_extraction_is_individual(self):
        c=self.w.definition('class','Support','Product help',True)
        self.w.definition('field','issue','Reported problem',True,parent=c)
        for id in self.ids[:2]: self.w.assign(id,c)
        self.job('fields','suggest fields',c,'running')
        self.job('classify','classify',self.ids[1],'running')
        rows=snapshot(self.w,self.batch)
        self.assertEqual(rows[0]['Classification'],'Complete')
        self.assertEqual(rows[1]['Classification'],'Running')
        for row in rows[:2]:
            self.assertEqual(row['Field suggestions'],'Running · Support (shared)')
        self.assertEqual(rows[2]['Field suggestions'],'Waiting for class assignment')
        self.s.save('extraction',{'fields':{'issue':{'value':'Broken','evidence':'broken'},'optional':{'value':None,'evidence':None}}},id='ex-'+self.ids[0],parent=self.ids[0],batch=self.batch)
        self.job('extract-failed','extract',self.ids[1],'failed','Temporary network error')
        rows=snapshot(self.w,self.batch)
        self.assertEqual(rows[0]['Extraction'],'Complete')
        self.assertEqual(rows[0]['Values'],1)
        self.assertEqual(rows[1]['Extraction'],'Failed')
        self.assertEqual(rows[2]['Extraction'],'Waiting for transcript')
        self.assertIn('network',rows[1]['Details'])
        self.assertNotIn('network',rows[0]['Details'])
