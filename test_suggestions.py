import unittest
from unittest.mock import patch
from audio_idp.services.class_suggestion import suggest_classes
from audio_idp.services.field_suggestion import suggest_fields

class SuggestionPromptTests(unittest.TestCase):
    def test_existing_taxonomy_can_require_no_new_classes(self):
        with patch('audio_idp.services.class_suggestion.request',return_value={'classes':[]}) as request:
            self.assertEqual(suggest_classes([{'id':'record-1','text':'Help with a printer'}],[{'name':'Support','description':'Product help','sources':['private-id']}]),[])
            prompt,payload=request.call_args.args
            self.assertIn('primary business purpose',prompt)
            self.assertIn('untrusted',prompt)
            self.assertIn('80 characters',prompt)
            self.assertIn('400 characters',prompt)
            self.assertNotIn('sources',payload['existing_classes'][0])

    def test_fields_are_definitions_not_answers_and_not_padded(self):
        with patch('audio_idp.services.field_suggestion.request',return_value={'fields':[]}) as request:
            self.assertEqual(suggest_fields({'name':'Support','description':'Product help','accepted':True},['Printer broken'],[]),[])
            prompt,payload=request.call_args.args
            self.assertIn('not extracted values',prompt)
            self.assertIn('no more than 10',prompt)
            self.assertIn('verbatim supporting quote',prompt)
            self.assertIn('Do not pad',prompt)
            self.assertEqual(set(payload['class']),{'name','description'})

    def test_invalid_or_oversized_suggestions_fail_validation(self):
        with patch('audio_idp.services.class_suggestion.request',return_value={'classes':[{'name':'x'*81,'description':'Test'}]}):
            with self.assertRaises(ValueError): suggest_classes([],[])
        with patch('audio_idp.services.field_suggestion.request',return_value={'fields':[{'name':str(n),'description':'Test'} for n in range(11)]}):
            with self.assertRaises(ValueError): suggest_fields({'name':'Support','description':'Help'},[],[])

    def test_class_suggestions_preserve_valid_recording_references(self):
        response={'classes':[{'name':'Support','description':'Product help','source_ids':['one']}],
                  'existing_matches':[{'name':'Sales','source_ids':['two']}]}
        with patch('audio_idp.services.class_suggestion.request',return_value=response):
            result=suggest_classes([{'id':'one','text':'Broken printer'},{'id':'two','text':'Buy a laptop'}],[{'name':'Sales','description':'Purchase questions'}])
        self.assertEqual(result[0]['source_ids'],['one'])
        self.assertEqual(result[1]['source_ids'],['two'])
        self.assertTrue(result[1]['existing'])
        response['classes'][0]['source_ids']=['unknown']
        with patch('audio_idp.services.class_suggestion.request',return_value=response):
            with self.assertRaisesRegex(ValueError,'recording references'):
                suggest_classes([{'id':'one','text':'Broken printer'}],[{'name':'Sales','description':'Purchase questions'}])
