"""Pure direct entry candidates; no real configuration, service or model requests."""
from pathlib import Path
import sys

ROOT = next(parent for parent in Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(ROOT / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

from copy import deepcopy
import json
import tempfile
import unittest
import operator_direct_profile as subject
import operator_native_models as native
from test_native_models import manifest

class DirectProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.model = manifest()
        self.before = b'# native owner\r\nmodel = "native-owner"\r\nmodel_reasoning_effort = "high"\r\n' \
            b'\r\n[features]\r\nshell_tool = true\r\n[unrelated]\r\nexact = "original"\r\n'

    def candidate(self, before=None, model=None):
        return subject.render(self.before if before is None else before,
            self.model if model is None else model, self.home)

    def test_direct_endpoint_model_catalog_and_original_permissions_are_exact(self):
        value = self.candidate()
        parsed = subject.parse(value.data)
        original = subject.parse(self.before)
        generated, provider = native.artifacts(self.model, self.home)
        profile = subject.parse(generated['profile'])
        self.assertEqual({key: parsed[key] for key in subject.SELECTORS},
            {key: profile[key] for key in subject.SELECTORS})
        self.assertEqual(parsed['model_providers'][provider], profile['model_providers'][provider])
        self.assertFalse(parsed['model_providers'][provider]['requires_openai_auth'])
        self.assertEqual(parsed['features'], original['features'])
        self.assertEqual(parsed['unrelated'], original['unrelated'])
        self.assertEqual(subject.restore(value.data, value.recovery), self.before)

    def test_later_unrelated_and_cua_edits_survive_recovery(self):
        value = self.candidate()
        later = value.data.replace(b'exact = "original"', b'exact = "later-owner"')
        later += b'\n[cua]\npipe = "new-live-pipe"\n'
        recovered = subject.restore(later, value.recovery)
        self.assertEqual(recovered, self.before.replace(b'exact = "original"',
            b'exact = "later-owner"') + b'\n[cua]\npipe = "new-live-pipe"\n')

    def test_bom_crlf_unicode_and_comment_bytes_roundtrip(self):
        before = subject.BOM + '# 所有者原件\r\n'.encode() + self.before
        value = self.candidate(before)
        self.assertTrue(value.data.startswith(subject.BOM))
        self.assertEqual(subject.restore(value.data, value.recovery), before)

    def test_wholly_commented_legacy_block_keeps_leading_exact_bytes(self):
        legacy = b'# BEGIN FEISHU OPERATOR MODEL ROUTER\r\n# openai_base_url = "http://127.0.0.1:54321/' + \
            b'a' * 64 + b'/v1"\r\n# END FEISHU OPERATOR MODEL ROUTER\r\n'
        before = legacy + self.before
        value = self.candidate(before)
        self.assertTrue(value.data.startswith(legacy + subject.BEGIN))
        self.assertEqual(subject.restore(value.data, value.recovery), before)

    def test_active_incomplete_duplicate_and_unknown_legacy_blocks_are_rejected(self):
        for before in (b'# BEGIN FEISHU OPERATOR MODEL ROUTER\n' + self.before,
            b'# END FEISHU OPERATOR MODEL ROUTER\n' + self.before,
            b'# BEGIN FEISHU OPERATOR MODEL ROUTER\nopenai_base_url="http://127.0.0.1:1/v1"\n'
            b'# END FEISHU OPERATOR MODEL ROUTER\n' + self.before):
            with self.subTest(before=before):
                with self.assertRaises(subject.DirectProfileError): self.candidate(before)

    def test_native_provider_baseline_and_official_urls_are_required(self):
        for extra in (b'model_provider="unknown"\n', b'openai_base_url="https://other.example/v1"\n',
            b'profile="obsolete-profile"\n'):
            with self.subTest(extra=extra):
                with self.assertRaises(subject.DirectProfileError): self.candidate(extra + self.before)
        value = self.candidate(b'model_provider="openai"\n' + self.before)
        self.assertEqual(subject.restore(value.data, value.recovery), b'model_provider="openai"\n' + self.before)

    def test_current_unified_route_cannot_be_silently_migrated(self):
        with self.assertRaises(subject.DirectProfileError):
            self.candidate(b'# BEGIN OPERATOR UNIFIED CANDIDATE\nmodel_provider="operator_unified_candidate"\n' + self.before)

    def test_existing_saved_markers_and_owned_provider_collision_are_rejected(self):
        for before in (subject.SAVED + self.before,
            self.before + b'[model_providers.operator_native_native_fixture]\nname="later-owner"\n'):
            with self.assertRaises(subject.DirectProfileError): self.candidate(before)

    def test_all_native_selectors_keep_their_exact_original_line(self):
        before = b'model="native" # original owner\nmodel_provider="openai"\n' \
            b'model_catalog_json="C:/explicit-original/catalog.json"\n' \
            b'model_reasoning_effort="high"\nweb_search="cached"\n'
        value = self.candidate(before)
        self.assertEqual(subject.restore(value.data, value.recovery), before)
        self.assertEqual(len(value.recovery['saved']), 5)

    def test_empty_native_config_and_explicit_empty_provider_table_roundtrip(self):
        for before in (b'', b'[model_providers]\n'):
            with self.subTest(before=before):
                value = self.candidate(before)
                self.assertEqual(subject.restore(value.data, value.recovery), before)

    def test_changed_selection_provider_or_original_selector_stops_recovery(self):
        value = self.candidate()
        for current in (value.data.replace(b'fixture/exact-model', b'later/exact-model', 1),
            value.data.replace(b'Synthetic', b'Something', 1) if b'Synthetic' in value.data else
                value.data.replace(b'Disposable fixture', b'Changed fixture'),
            value.data.replace(subject.SAVED + b'model = "native-owner"',
                subject.SAVED + b'model = "later-owner"')):
            with self.subTest(current=current):
                with self.assertRaises(subject.DirectProfileError): subject.restore(current, value.recovery)

    def test_partial_duplicate_marker_and_saved_line_are_rejected(self):
        value = self.candidate()
        for current in (value.data.replace(subject.PROVIDER_END, b''), value.data + subject.BEGIN,
            value.data + subject.SAVED + b'model = "native-owner"\r\n'):
            with self.assertRaises(subject.DirectProfileError): subject.restore(current, value.recovery)

    def test_multiline_selector_or_missing_final_newline_cannot_be_normalized(self):
        for before in (b'model="""native\nowner"""\n', b'model="native"',
            b'"model"="native"\n'):
            with self.subTest(before=before):
                with self.assertRaises(subject.DirectProfileError): self.candidate(before)

    def test_size_invalid_toml_and_relative_home_fail_before_projection(self):
        for before in (b'a' * (subject.LIMIT + 1), b'model=oops\n', b'\xff\n'):
            with self.assertRaises(subject.DirectProfileError): self.candidate(before)
        with self.assertRaises(subject.DirectProfileError): subject.render(self.before, self.model, Path('relative'))

    def test_recovery_record_cannot_erase_or_insert_unrelated_settings(self):
        value = self.candidate()
        records = []
        forged = deepcopy(value.recovery)
        forged['saved'][0]['line_hex'] = b'model="native"\n[other]\nsetting="invented"\n'.hex()
        records.append(forged)
        forged = deepcopy(value.recovery); forged['prefix_hex'] = b''.hex(); records.append(forged)
        forged = deepcopy(value.recovery); forged['provider_id'] = 'openai'; records.append(forged)
        forged = deepcopy(value.recovery); forged['leading_hex'] = b'unknown-owner-bytes'.hex(); records.append(forged)
        for record in records:
            with self.subTest(record=record):
                with self.assertRaises(subject.DirectProfileError): subject.restore(value.data, record)

    def test_preview_is_readonly_and_binds_the_installed_profile(self):
        config = self.home / 'config.toml'; config.write_bytes(self.before)
        source = self.home / 'manifest.json'; source.write_bytes(native.json_bytes(self.model))
        state = self.home / 'registration'
        native.prepare(state, self.home, source); native.install(state, self.home)
        before = {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()}
        result = subject.preview(state, self.home)
        self.assertEqual(result['status'], 'preview')
        self.assertFalse(result['router_required'])
        self.assertEqual(result['model_requests'], 0)
        self.assertFalse(result['configuration_changed'])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()})

    def test_altered_installed_profile_cannot_be_previewed(self):
        (self.home / 'config.toml').write_bytes(self.before)
        source = self.home / 'manifest.json'; source.write_bytes(native.json_bytes(self.model))
        state = self.home / 'registration'
        native.prepare(state, self.home, source); native.install(state, self.home)
        (self.home / (self.model['profile'] + '.config.toml')).write_bytes(b'model="later-edit"\n')
        with self.assertRaises(subject.DirectProfileError): subject.preview(state, self.home)

if __name__ == '__main__':
    unittest.main()
