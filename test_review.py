import tempfile
import time
import unittest
from unittest.mock import patch
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace
from audio_idp.services.review import candidates,link_manual

class ProvenanceTests(unittest.TestCase):
    def test_refresh_replaces_only_real_file_matches_and_edits_stale_them(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Workspace(Store(folder));s=w.store
            try:
                batch=w.batch('Provenance')
                ids=[]
                for i in range(2):
                    w.upload(batch,str(i)+'.wav',str(i).encode(),'English')
                    r=s.list('recording',batch=batch)[-1];ids.append(r['id'])
                    s.save('transcript',{'text':str(i),'language':'en','segments':[]},id='tr-'+r['id'],parent=r['id'],batch=batch)
                def wait():
                    deadline=time.monotonic()+5
                    while any(not f.done() for f in w.jobs.futures):
                        if time.monotonic()>deadline:self.fail('Jobs timed out')
                        time.sleep(.01)
                rows=[{'name':'Support','description':'Product help','source_ids':[ids[0]]},
                      {'name':'Sales','description':'Purchase questions','source_ids':[ids[1]]}]
                with patch('audio_idp.workflow.coordinator.suggest_classes',return_value=rows):w.suggest_classes(batch);wait()
                self.assertEqual([c['data']['name'] for c in candidates(s,ids[0])],['Support'])
                self.assertEqual([c['data']['name'] for c in candidates(s,ids[1])],['Sales'])
                support=candidates(s,ids[0])[0]
                w.edit_transcript(s.get('tr-'+ids[0]),'Changed text')
                self.assertFalse(candidates(s,ids[0]))
                with patch('audio_idp.workflow.coordinator.suggest_classes',return_value=[dict(rows[0],source_ids=[ids[1]])]):w.suggest_classes(batch);wait()
                self.assertFalse(candidates(s,ids[0]))
                self.assertEqual([c['data']['name'] for c in candidates(s,ids[1])],['Support'])
                link_manual(s,ids[0],support['id'])
                with patch('audio_idp.workflow.coordinator.suggest_classes',return_value=[]):w.suggest_classes(batch);wait()
                self.assertEqual([c['data']['name'] for c in candidates(s,ids[0])],['Support'])
                self.assertFalse(candidates(s,ids[1]))
            finally:
                w.jobs.audio.shutdown(wait=True);w.jobs.cloud.shutdown(wait=True)
