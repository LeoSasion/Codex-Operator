import hashlib
import unittest
from unittest.mock import patch

from operator_core import lmstudio_template as template
from operator_core.model_registry import RouterError


class LMStudioTemplateTests(unittest.TestCase):
    def setUp(self):
        self.original = 'unchanged user/assistant/tool branch\n' + template._REJECT + '\nunchanged suffix'
        self.digest = hashlib.sha256(self.original.encode()).hexdigest()

    def test_unknown_template_is_rejected(self):
        with self.assertRaisesRegex(RouterError, 'source_changed'):
            template.huihui_candidate(self.original)

    def test_only_selected_branch_changes(self):
        with patch.object(template, 'HUIHUI_SOURCE_SHA256', self.digest):
            candidate = template.huihui_candidate(self.original)
        self.assertEqual(candidate, self.original.replace(template._REJECT, template._ORDERED_BLOCK, 1))
        self.assertIn('render_content(message.content, false, true)', candidate)
        self.assertNotIn('|trim', candidate)

    def test_missing_or_duplicate_branch_is_rejected_even_with_digest(self):
        for original in ('without branch', self.original + template._REJECT):
            with self.subTest(original=original):
                with patch.object(template, 'HUIHUI_SOURCE_SHA256', hashlib.sha256(original.encode()).hexdigest()):
                    with self.assertRaisesRegex(RouterError, 'source_changed'):
                        template.huihui_candidate(original)

    def test_prepare_preserves_source_and_stop_strings(self):
        original = {'promptTemplate': {'type': 'jinja', 'jinjaPromptTemplate': {'template': self.original},
            'stopStrings': ['literal stop\n', '中文']}, 'other_runtime_setting': {'untouched': True}}
        with patch.object(template, 'HUIHUI_SOURCE_SHA256', self.digest):
            result = template.huihui_model_defaults(original)
        prediction = result['operation']['fields'][0]['value']
        loading = result['load']['fields'][0]['value']
        self.assertEqual(prediction['stopStrings'], original['promptTemplate']['stopStrings'])
        self.assertEqual(prediction['jinjaPromptTemplate'], loading['jinjaPromptTemplate'])
        self.assertEqual(original['promptTemplate']['jinjaPromptTemplate']['template'], self.original)
        prediction['stopStrings'].append('changed candidate')
        self.assertEqual(original['promptTemplate']['stopStrings'], ['literal stop\n', '中文'])

    def test_unknown_prompt_fields_and_malformed_stops_are_not_dropped(self):
        for prompt in ({'type': 'jinja', 'jinjaPromptTemplate': {'template': self.original}, 'stopStrings': [], 'unknown': 1},
                       {'type': 'jinja', 'jinjaPromptTemplate': {'template': self.original}, 'stopStrings': [False]}):
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(RouterError, 'config_invalid'):
                    template.huihui_model_defaults({'promptTemplate': prompt})

    def test_separate_load_representation_is_preserved(self):
        load_source = self.original + '\noriginal engine tojson safe filter'
        prediction = {'promptTemplate': {'type':'jinja',
            'jinjaPromptTemplate':{'template':self.original},'stopStrings':[]}}
        loading = {'promptTemplate': {'type':'jinja','jinjaPromptTemplate':{'template':load_source}},
                   'contextLength':32768,'maxParallelPredictions':4}
        with patch.object(template,'HUIHUI_SOURCE_SHA256',self.digest), \
                patch.object(template,'HUIHUI_LOAD_SOURCE_SHA256',hashlib.sha256(load_source.encode()).hexdigest()):
            result = template.huihui_model_defaults(prediction,loading)
        self.assertEqual(result['load']['fields'][0]['value']['jinjaPromptTemplate']['template'],
                         load_source.replace(template._REJECT,template._ORDERED_BLOCK,1))
        self.assertEqual(loading['promptTemplate']['jinjaPromptTemplate']['template'],load_source)
        self.assertEqual(loading['contextLength'],32768)

    def test_unknown_load_representation_and_fields_are_rejected(self):
        prediction = {'promptTemplate': {'type':'jinja',
            'jinjaPromptTemplate':{'template':self.original},'stopStrings':[]}}
        for loading in ({'promptTemplate':{'type':'jinja','jinjaPromptTemplate':{'template':'unknown'}}},
                        {'promptTemplate':{'type':'jinja','jinjaPromptTemplate':{'template':self.original},'unknown':1}}):
            with self.subTest(loading=loading), patch.object(template,'HUIHUI_SOURCE_SHA256',self.digest):
                with self.assertRaises(RouterError):
                    template.huihui_model_defaults(prediction,loading)


if __name__ == '__main__':
    unittest.main()
