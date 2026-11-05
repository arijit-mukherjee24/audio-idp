import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from audio_idp.persistence.database import Store
from audio_idp.services.job_execution import execution_metadata,response_source
from audio_idp.workflow.coordinator import Workspace


class JobExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Store(self.temp.name);self.w=Workspace(self.s)
        self.batch=self.w.batch('Provider audit')
        self.w.upload(self.batch,'audio.wav',b'synthetic recording','English')
        self.recording=self.s.list('recording',batch=self.batch)[0]
    def tearDown(self):
        self.w.jobs.audio.shutdown(wait=True);self.w.jobs.cloud.shutdown(wait=True);self.temp.cleanup()
    def wait(self):
        for future in tuple(self.w.jobs.futures):future.result(timeout=5)

    def test_azure_job_persists_real_provider_and_request_details(self):
        result={'text':'Synthetic transcript','language':'en','provider':'azure',
                'azure_api_version':'2025-10-15','azure_endpoint':'https://example.cognitiveservices.azure.com',
                'azure_http_status':200,'azure_request_id':'request-123','azure_request_sent_at':'2026-11-05T00:00:00+00:00',
                'AZURE_SPEECH_KEY':'must-not-enter-job-history'}
        with patch('audio_idp.workflow.coordinator.transcribe',return_value=result):
            self.w.transcribe_batch(self.batch,provider='azure');self.wait()
        job=self.s.jobs(self.batch)[0]
        self.assertEqual(job['provider'],'azure')
        self.assertEqual(job['execution']['http_status'],200)
        self.assertEqual(job['execution']['request_id'],'request-123')
        self.assertEqual(response_source(job),'Azure API · HTTP 200')
        self.assertIsNone(job['request_hash'])
        self.assertNotIn('must-not-enter-job-history',json.dumps(job))
        self.assertNotIn('Synthetic transcript',json.dumps(job))
        snapshot=json.loads(self.w.snapshots.path(self.batch).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['jobs'][0]['execution']['request_id'],'request-123')
        self.w.transcribe_batch(self.batch,provider='whisper');self.wait()
        self.assertEqual(self.s.jobs(self.batch)[0]['provider'],'azure')
        self.assertEqual(len(self.s.jobs(self.batch)),1)

    def test_failed_azure_job_keeps_selected_provider_without_fake_http_success(self):
        with patch('audio_idp.workflow.coordinator.transcribe',side_effect=ValueError('Azure Speech returned HTTP 401.')):
            self.w.transcribe_batch(self.batch,provider='azure');self.wait()
        job=self.s.jobs(self.batch)[0]
        self.assertEqual(job['status'],'failed');self.assertEqual(job['provider'],'azure')
        self.assertEqual(job['execution'],{})
        self.assertNotIn('200',response_source(job))

    def test_execution_metadata_excludes_credentials_and_unsafe_urls(self):
        data={'text':'private text','headers':{'Authorization':'private'},'azure_endpoint':'https://example.com?key=private',
              'azure_http_status':200,'azure_api_version':'2025-10-15'}
        result=execution_metadata('transcribe',data)
        self.assertEqual(result,{'http_status':200,'api_version':'2025-10-15'})
        self.assertEqual(execution_metadata('extract',data),{})
        self.assertEqual(response_source({'status':'completed','provider':'whisper'}),'Local transcription')
        self.assertEqual(response_source({'status':'completed'}),'Not recorded (older job)')
        self.assertEqual(response_source({'status':'completed','request_hash':'hash','cache_hit':1}),'Cached response')

    def test_rule_based_assignment_does_not_claim_a_bedrock_api_call(self):
        self.w.jobs.submit('classify',self.recording['id'],self.batch,[],
                           lambda:{'source':'accepted_suggestion'},lambda value:None)
        self.wait()
        job=self.s.jobs(self.batch)[0]
        self.assertEqual(job['provider'],'local')
        self.assertEqual(response_source(job),'Local processing')


class JobExecutionMigrationTests(unittest.TestCase):
    def test_v4_jobs_survive_migration_without_invented_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            migrations=Path(__file__).parent/'audio_idp'/'persistence'/'migrations'
            with closing(sqlite3.connect(Path(folder)/'audio-idp.sqlite3')) as db:
                for name in ('001_initial.sql','002_batch_snapshots.sql','003_snapshot_trigger_upserts.sql','004_converse_cache.sql'):
                    db.executescript((migrations/name).read_text(encoding='utf-8'))
                db.execute("INSERT INTO jobs(id,kind,target,batch,status,created,updated) VALUES('legacy','transcribe','file','batch','completed',1,2)")
                db.commit()
            store=Store(folder)
            job=store.jobs()[0]
            self.assertEqual(job['id'],'legacy');self.assertEqual(job['status'],'completed')
            self.assertIsNone(job['provider']);self.assertEqual(job['execution'],{})
            with store.connection() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)
