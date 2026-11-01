import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from audio_idp.persistence.database import Store
from audio_idp.providers.bedrock import ask_json
from audio_idp.providers.response_cache import ResponseCache,cache_scope,fingerprint
from audio_idp.workflow.coordinator import Workspace

class Runtime:
    def __init__(self):self.calls=0;self.text='{"value":"answer"}';self.stop='end_turn'
    def converse(self,**kwargs):
        self.calls+=1
        return {'stopReason':self.stop,'output':{'message':{'content':[{'text':self.text}]}}}

class ResponseCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.cache=ResponseCache(self.store);self.runtime=Runtime()
        self.batch=self.store.save('batch',{'name':'Cache test'})
        self.record=self.store.save('recording',{'name':'test.wav','path':str(self.store.uploads/'test.wav')},batch=self.batch)
    def tearDown(self):self.temp.cleanup()
    def ask(self,*,refresh=False,task='task',data=None,model='model',runtime=None):
        with cache_scope(self.cache,bypass=refresh,owners={(self.batch,self.record)}) as context:
            result=ask_json(runtime or self.runtime,model,task,{'text':'Same content'} if data is None else data)
            context.commit()
            return result,context.hits
    def test_persistent_hits_and_lazy_credentials(self):
        self.ask()
        self.cache=ResponseCache(Store(self.temp.name))
        def unavailable():raise AssertionError('Cache hit should not load AWS credentials')
        result,hits=self.ask(runtime=unavailable)
        self.assertEqual(result,{'value':'answer'});self.assertEqual(hits,1);self.assertEqual(self.runtime.calls,1)
    def test_content_prompt_model_and_explicit_refresh(self):
        self.ask();self.ask();self.assertEqual(self.runtime.calls,1)
        self.ask(data={'text':'Edited content'});self.ask(task='Updated prompt');self.ask(model='new-model')
        self.assertEqual(self.runtime.calls,4)
        self.runtime.text='{"value":"refreshed"}';self.ask(refresh=True)
        result,hits=self.ask();self.assertEqual(result['value'],'refreshed');self.assertEqual(hits,1)
        self.assertEqual(self.runtime.calls,5)
    def test_canonical_hash_and_defensive_copies(self):
        self.assertEqual(fingerprint({'a':1,'b':2}),fingerprint({'b':2,'a':1}))
        result,_=self.ask();result['value']='changed'
        self.assertEqual(self.ask()[0]['value'],'answer')
    def test_invalid_or_unvalidated_outputs_are_not_saved(self):
        self.runtime.text='not JSON'
        with self.assertRaises(ValueError):self.ask()
        self.runtime.text='{}';self.runtime.stop='max_tokens'
        with self.assertRaises(ValueError):self.ask()
        self.runtime.stop='end_turn'
        with self.assertRaises(ValueError):
            with cache_scope(self.cache):
                ask_json(self.runtime,'model','task',{})
                raise ValueError('Domain validation rejected the response')
        self.assertEqual(self.cache.stats()['entries'],0)
    def test_identical_concurrent_requests_only_invoke_once(self):
        barrier=threading.Barrier(3)
        def work():barrier.wait(timeout=3);return self.ask()
        with ThreadPoolExecutor(3) as pool:results=list(pool.map(lambda _:work(),range(3)))
        self.assertEqual(self.runtime.calls,1);self.assertEqual(sum(hits for _,hits in results),2)
    def test_clear_prevents_inflight_repopulation_and_delete_removes_content(self):
        with cache_scope(self.cache,owners={(self.batch,self.record)}) as context:
            ask_json(self.runtime,'model','task',{})
            self.cache.clear();context.commit()
        self.assertEqual(self.cache.stats()['entries'],0)
        self.ask();self.store.delete(self.record)
        self.assertEqual(self.cache.stats()['entries'],0)
        self.ask();self.store.reset()
        self.assertEqual(self.cache.stats()['entries'],0)
    def test_validated_job_cache_and_job_metadata(self):
        w=Workspace(self.store)
        def wait():
            deadline=time.monotonic()+5
            while any(not f.done() for f in w.jobs.futures):
                if time.monotonic()>deadline:self.fail('Job timed out')
                time.sleep(.01)
        try:
            def work():return ask_json(self.runtime,'model','task',{})
            for i in range(2):
                w.jobs.submit('AI',self.record,self.batch,[],work,lambda value:None);wait()
            jobs=self.store.jobs()
            self.assertEqual(self.runtime.calls,1)
            self.assertEqual(sum(j['cache_hit'] for j in jobs),1)
            self.assertTrue(all(j['request_hash'] and j['status']=='completed' for j in jobs))
            def invalid():work();raise ValueError('Rejected')
            w.jobs.cache.clear()
            w.jobs.submit('AI',self.record,self.batch,[],invalid,lambda value:None);wait()
            self.assertEqual(w.jobs.cache.stats()['entries'],0)
        finally:w.jobs.audio.shutdown(wait=True);w.jobs.cloud.shutdown(wait=True)

