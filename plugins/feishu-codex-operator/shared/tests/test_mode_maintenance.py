"""A stopped focus denial remains failed; only its exact receipt is reviewable."""
from unittest.mock import patch

from test_mode_entry import ModeEntryTests, mode
import operator_mode_maintenance as maintenance


class ModeMaintenanceTests(ModeEntryTests):
    def official_upgrade(self):
        family = 'OpenAI.Codex_fixturepublisher'
        def package(version):
            executable = self.base / version / 'ChatGPT.exe'
            executable.parent.mkdir()
            executable.write_bytes(('official package fixture ' + version).encode())
            return {'family': family, 'version': version,
                    'full_name': 'OpenAI.Codex_' + version + '_x64__fixturepublisher',
                    'executable': str(executable), 'executable_sha256': mode.file_hash(executable)}
        self.package = package('26.928.3735.0')
        return package('26.930.2377.0')

    def absent_router(self):
        attempt = self.root / 'router-launches' / ('d' * 32)
        attempt.mkdir()
        mode.write_new(attempt / 'intent.json', {'started_utc': mode.utc(), 'native_enabled': False})
        mode.write_new(attempt / 'running.json', {'process': {'pid': 17, 'birth': '123', 'executable': 'fixture'},
                                                'service': '1' * 64})
        return attempt

    def test_official_upgrade_requires_explicit_bound_pair_and_preserves_existing_home(self):
        current = self.official_upgrade()
        self.installed_mode()
        mode.write_new(self.root / 'home/history.jsonl', b'complete history and failed turns\n')
        before = {p: p.read_bytes() for p in (self.root / 'home').iterdir()}
        entry = (self.root / 'entry.json').read_bytes()
        with patch.object(mode, 'inspect_package', return_value=current), \
                patch.object(maintenance, 'isolated_processes_absent'), \
                patch.object(maintenance, 'activation_hosts_absent'):
            with self.assertRaisesRegex(mode.ModeEntryError, 'official_package_changed'):
                maintenance.pair_prepare(self.root, compiler=self.compiler)
            with self.assertRaisesRegex(mode.ModeEntryError, 'requires_bound_upgrade'):
                mode.refresh_snapshot(self.root, package_update=True)
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler, package_update=True)['stage'])
            plan, manifest = maintenance.pair_stage(self.root, stage)
            candidate = mode.decode(mode.read(stage / 'staged/entry.json'))
            self.assertEqual(candidate['package'], current)
            self.assertFalse(candidate['onboarding']['supported'])
            self.assertEqual(plan['package_update'], manifest['package_update'])
            self.assertEqual((stage / 'originals/entry.json').read_bytes(), entry)
            self.assertEqual((self.root / 'entry.json').read_bytes(), entry)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_changed_package_during_compile_retains_failed_generation_without_publication(self):
        current = self.official_upgrade()
        self.installed_mode()
        before = (self.root / 'entry.json').read_bytes()
        changed = dict(current, executable_sha256='9' * 64)
        with patch.object(mode, 'inspect_package', side_effect=[current, changed]), \
                patch.object(maintenance, 'isolated_processes_absent'), \
                patch.object(maintenance, 'activation_hosts_absent'):
            with self.assertRaisesRegex(mode.ModeEntryError, 'pair_prepare_baseline_changed'):
                maintenance.pair_prepare(self.root, compiler=self.compiler, package_update=True)
        self.assertEqual((self.root / 'entry.json').read_bytes(), before)
        self.assertTrue(next((self.root / 'pair-refreshes').iterdir()).joinpath('failed.json').is_file())
        with self.assertRaisesRegex(mode.ModeEntryError, 'previous_pair_refresh_uncertain_no_retry'):
            mode.load(self.root)

    def test_package_update_rejects_changed_family_downgrade_and_altered_manifest(self):
        current = self.official_upgrade()
        self.installed_mode()
        with self.assertRaisesRegex(mode.ModeEntryError, 'not_same_family_upgrade'):
            mode.package_update_snapshot(current, self.package)
        other = dict(current, family='OpenAI.Codex_other', full_name='OpenAI.Codex_26.930.2377.0_x64__other')
        with self.assertRaisesRegex(mode.ModeEntryError, 'not_same_family_upgrade'):
            mode.package_update_snapshot(self.package, other)
        with patch.object(mode, 'inspect_package', return_value=current), \
                patch.object(maintenance, 'isolated_processes_absent'), \
                patch.object(maintenance, 'activation_hosts_absent'):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler, package_update=True)['stage'])
            manifest = mode.decode(mode.read(stage / 'prepared.json'))
            manifest['package_update']['before']['executable_sha256'] = '8' * 64
            (stage / 'prepared.json').write_bytes(mode.json_bytes(manifest))
            with self.assertRaisesRegex(mode.ModeEntryError, 'pair_stage_invalid'):
                maintenance.pair_stage(self.root, stage)

    def test_router_absence_review_is_distinct_terminal_and_preserves_original_generation(self):
        self.installed_mode()
        attempt = self.absent_router()
        originals = {p: p.read_bytes() for p in attempt.iterdir()}
        with patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'isolated_processes_absent'), \
                patch.object(maintenance, 'activation_hosts_absent'):
            preview = maintenance.review_router_absence(self.root)
            self.assertFalse((attempt / 'absence-original-entry.json').exists())
            with self.assertRaisesRegex(mode.ModeEntryError, 'preview_changed'):
                maintenance.review_router_absence(self.root, '0' * 64)
            result = maintenance.review_router_absence(self.root, preview['preview_sha256'])
            self.assertFalse(result['normal_stop_claimed'])
            self.assertTrue(mode.router_terminal(self.root, attempt))
            self.assertFalse((attempt / 'stopped.json').exists())
            with patch.object(mode, 'inspect_package', return_value=self.package):
                plan = mode.refresh_snapshot(self.root, bound_pair=True)
                self.assertIn(str(attempt / 'absence-reviewed.json'), plan['protected_files'])
            with (attempt / 'running.json').open('ab') as stream:
                stream.write(b'\n')
            with self.assertRaisesRegex(mode.ModeEntryError, 'review_changed'):
                mode.router_terminal(self.root, attempt)
        self.assertEqual((attempt / 'intent.json').read_bytes(), originals[attempt / 'intent.json'])
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_router_absence_rejects_live_process_and_consumed_stop_or_partial_review(self):
        self.installed_mode()
        attempt = self.absent_router()
        with patch.object(mode, 'process_matches', return_value=True), \
                patch.object(maintenance, 'isolated_processes_absent'), \
                patch.object(maintenance, 'activation_hosts_absent'):
            with self.assertRaisesRegex(mode.ModeEntryError, 'process_running_or_unknown'):
                maintenance.review_router_absence(self.root)
        with patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'isolated_processes_absent'), \
                patch.object(maintenance, 'activation_hosts_absent'):
            mode.write_new(attempt / 'stop-intent.json', {})
            with self.assertRaisesRegex(mode.ModeEntryError, 'not_reviewable'):
                maintenance.review_router_absence(self.root)
            (attempt / 'stop-intent.json').unlink()
            mode.write_new(attempt / 'absence-original-entry.json', mode.load(self.root, check_source=False))
            with self.assertRaisesRegex(mode.ModeEntryError, 'not_fresh'):
                maintenance.review_router_absence(self.root)

    def startup_failure(self):
        self.prepare()
        descriptor = mode.load(self.root)
        plan = mode.host_plan(self.root, descriptor)
        directory = self.root / 'launches' / ('d' * 32)
        directory.mkdir()
        mode.write_new(directory / 'intent.json', {'contract': mode.CONTRACT, 'start_service': True})
        mode.write_new(directory / 'dispatched.json', {'accepted': True})
        mode.write_new(directory / 'host-plan.json', plan)
        mode.write_new(self.root / 'host-plan.json', plan)
        mode.write_new(directory / 'host-starting.json', {'contract': mode.HOST_CONTRACT,
            'plan_sha256': mode.file_hash(directory / 'host-plan.json'),
            'package_identity': plan['package_full_name'],
            'native_config_sha256': mode.file_hash(self.native / 'config.toml')})
        mode.write_new(directory / 'host-failed.json', {'reason': 'mode_host_failed',
            'desktop_launched': True, 'hresult': -2147467261,
            'automatically_retried': False, 'desktop_terminated': False})
        mode.write_new(directory / 'controller-failed.json', {'reason': 'mode_host_failed',
            'automatically_retried': False})
        return directory

    def test_early_failure_review_retains_originals_and_allows_a_separate_live_launch(self):
        directory = self.startup_failure()
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with self.assertRaisesRegex(mode.ModeEntryError, 'previous_launch_running_or_uncertain'):
            mode.active_desktop(self.root)
        with patch.object(maintenance, 'startup_processes_absent'):
            preview = maintenance.review_startup(self.root, directory.name)
            self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
            with self.assertRaisesRegex(mode.ModeEntryError, 'preview_changed'):
                maintenance.review_startup(self.root, directory.name, '0' * 64)
            maintenance.review_startup(self.root, directory.name, preview['preview_sha256'])
            self.assertTrue(maintenance.reviewed_startup_failure(self.root, directory))
            self.assertIsNone(mode.active_desktop(self.root))
            maintenance.stopped_desktops(self.root)
            with self.assertRaisesRegex(mode.ModeEntryError, 'already_retained'):
                maintenance.review_startup(self.root, directory.name, preview['preview_sha256'])
        launch, process = self.started_attempt()
        with patch.object(mode, 'process_matches', return_value=True):
            self.assertEqual(mode.active_desktop(self.root)[0], launch)
        self.assertFalse((directory / 'desktop-started.json').exists())
        self.assertFalse((directory / 'desktop-exited.json').exists())
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()
                          if p.name != 'startup-reviewed.json'}, before)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_early_failure_review_rejects_live_processes_and_changed_current_files(self):
        directory = self.startup_failure()
        with patch.object(maintenance, 'startup_processes_absent',
                          side_effect=mode.ModeEntryError('startup_process_still_running_or_unknown')):
            with self.assertRaisesRegex(mode.ModeEntryError, 'still_running_or_unknown'):
                maintenance.review_startup(self.root, directory.name)
        self.assertFalse((directory / 'startup-reviewed.json').exists())
        with patch.object(maintenance, 'startup_processes_absent'):
            preview = maintenance.review_startup(self.root, directory.name)
            (self.native / 'config.toml').write_bytes(b'# later owner edit\n')
            with self.assertRaisesRegex(mode.ModeEntryError, 'baseline_changed'):
                maintenance.review_startup(self.root, directory.name, preview['preview_sha256'])
        self.assertFalse((directory / 'startup-reviewed.json').exists())
        self.assertEqual((self.native / 'config.toml').read_bytes(), b'# later owner edit\n')

    def test_early_failure_review_binds_and_preserves_current_extension_choices(self):
        directory = self.startup_failure()
        with (self.root / 'home/config.toml').open('ab') as stream:
            stream.write(b'\n# Desktop persisted choice\n')
        preserved = (self.root / 'home/config.toml').read_bytes()
        with patch.object(maintenance, 'startup_processes_absent'):
            preview = maintenance.review_startup(self.root, directory.name)
            with (self.root / 'home/config.toml').open('ab') as stream:
                stream.write(b'# later choice after preview\n')
            with self.assertRaisesRegex(mode.ModeEntryError, 'preview_changed'):
                maintenance.review_startup(self.root, directory.name, preview['preview_sha256'])
            self.assertFalse((directory / 'startup-reviewed.json').exists())
            (self.root / 'home/config.toml').write_bytes(preserved)
            maintenance.review_startup(self.root, directory.name, preview['preview_sha256'])
        self.assertEqual((self.root / 'home/config.toml').read_bytes(), preserved)

    def test_early_failure_review_rechecks_after_process_observation(self):
        directory = self.startup_failure()
        def changed(root, descriptor):
            (self.native / 'config.toml').write_bytes(b'# owner edit during read-only observation\n')
        with patch.object(maintenance, 'startup_processes_absent', side_effect=changed):
            with self.assertRaisesRegex(mode.ModeEntryError, 'baseline_changed'):
                maintenance.review_startup(self.root, directory.name)
        self.assertFalse((directory / 'startup-reviewed.json').exists())
        self.assertEqual((self.native / 'config.toml').read_bytes(),
                         b'# owner edit during read-only observation\n')

    def test_early_failure_review_rejects_other_errors_partial_records_and_changed_failure(self):
        directory = self.startup_failure()
        original = (directory / 'host-failed.json').read_bytes()
        failure = mode.decode(original)
        failure['hresult'] = -2147467259
        (directory / 'host-failed.json').write_bytes(mode.json_bytes(failure))
        with self.assertRaisesRegex(mode.ModeEntryError, 'not_reviewable'):
            maintenance.startup_failure_snapshot(self.root, directory.name)
        (directory / 'host-failed.json').write_bytes(original)
        mode.write_new(directory / 'desktop-started.json', {'pid': 99})
        with self.assertRaisesRegex(mode.ModeEntryError, 'not_reviewable'):
            maintenance.startup_failure_snapshot(self.root, directory.name)
        (directory / 'desktop-started.json').unlink()
        with patch.object(maintenance, 'startup_processes_absent'):
            preview = maintenance.review_startup(self.root, directory.name)
            maintenance.review_startup(self.root, directory.name, preview['preview_sha256'])
        with (directory / 'host-failed.json').open('ab') as stream:
            stream.write(b'\n')
        with self.assertRaisesRegex(mode.ModeEntryError, 'review_changed'):
            mode.active_desktop(self.root)

    def focus_failure(self):
        self.prepare()
        launch, process = self.started_attempt()
        mode.write_new(launch / 'host-plan.json', {'fixture': 'no launch'})
        mode.write_new(launch / 'desktop-exited.json', {'pid': process['pid'], 'exit_code': 0,
            'window_was_bound': True, 'native_config_unchanged': True})
        directory = self.root / 'activations' / ('e' * 32)
        directory.mkdir()
        mode.write_new(directory / 'intent.json', {'original_pid': process['pid'], 'attempt': launch.name,
            'plan_sha256': mode.file_hash(launch / 'host-plan.json')})
        mode.write_new(directory / 'host-starting.json', {'original_pid': process['pid']})
        mode.write_new(directory / 'failed.json', {'reason': 'mode_foreground_not_granted',
                                                'automatically_retried': False})
        mode.write_new(directory / 'controller-failed.json', {'reason': 'mode_foreground_not_granted'})
        return directory

    def test_focus_review_preserves_failure_and_requires_exact_stopped_snapshot(self):
        directory = self.focus_failure()
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'activation_hosts_absent'):
            preview = maintenance.review_focus(self.root, directory.name)
            self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
            with self.assertRaisesRegex(mode.ModeEntryError, 'preview_changed'):
                maintenance.review_focus(self.root, directory.name, '0' * 64)
            maintenance.review_focus(self.root, directory.name, preview['preview_sha256'])
            self.assertTrue(maintenance.reviewed_focus_failure(self.root, directory))
            maintenance.stopped_desktops(self.root)
            with self.assertRaisesRegex(mode.ModeEntryError, 'already_retained'):
                maintenance.review_focus(self.root, directory.name, preview['preview_sha256'])
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir() if p.name != 'focus-reviewed.json'}, before)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_live_original_or_forwarder_or_other_failure_cannot_be_reviewed(self):
        directory = self.focus_failure()
        with patch.object(mode, 'process_matches', return_value=True):
            with self.assertRaisesRegex(mode.ModeEntryError, 'requires_normal_exit'):
                maintenance.focus_failure_snapshot(self.root, directory.name)
        mode.write_new(directory / 'forwarder.json', {'pid': 77})
        with self.assertRaisesRegex(mode.ModeEntryError, 'not_reviewable'):
            maintenance.focus_failure_snapshot(self.root, directory.name)
        (directory / 'forwarder.json').unlink()
        (directory / 'failed.json').write_bytes(mode.json_bytes({'reason': 'mode_window_reopen_unconfirmed',
                                                               'automatically_retried': False}))
        with self.assertRaisesRegex(mode.ModeEntryError, 'not_reviewable'):
            maintenance.focus_failure_snapshot(self.root, directory.name)

    def test_changed_retained_failure_invalidates_review(self):
        directory = self.focus_failure()
        with patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'activation_hosts_absent'):
            preview = maintenance.review_focus(self.root, directory.name)
            maintenance.review_focus(self.root, directory.name, preview['preview_sha256'])
            with (directory / 'host-starting.json').open('ab') as stream:
                stream.write(b'\n')
            with self.assertRaisesRegex(mode.ModeEntryError, 'review_changed'):
                maintenance.reviewed_focus_failure(self.root, directory)

    def installed_mode(self):
        self.prepare()
        directory = self.project / '.codex/operator-desktop-entry'
        directory.mkdir()
        mode.write_new(directory / 'desktop-entry.json', {'mode': 'isolated_mode',
            'startup_bundle': self.root.relative_to(self.project).as_posix()})

    def test_pair_staging_preserves_live_files_and_rejects_changed_descriptor(self):
        self.installed_mode()
        before = {name: (self.root / name).read_bytes() for name in maintenance.PAIR_FILES}
        with patch.object(mode, 'inspect_package', return_value=self.package):
            result = maintenance.pair_prepare(self.root, compiler=self.compiler)
            stage = mode.Path(result['stage'])
            maintenance.pair_stage(self.root, stage)
            self.assertEqual({name: (self.root / name).read_bytes() for name in maintenance.PAIR_FILES}, before)
            value = mode.decode(mode.read(stage / 'staged/entry.json'))
            value['native_home'] = str(self.root / 'home')
            (stage / 'staged/entry.json').write_bytes(mode.json_bytes(value))
            manifest = mode.decode(mode.read(stage / 'prepared.json'))
            manifest['files']['entry.json']['after'] = mode.file_hash(stage / 'staged/entry.json')
            (stage / 'prepared.json').write_bytes(mode.json_bytes(manifest))
            with self.assertRaisesRegex(mode.ModeEntryError, 'descriptor_changed'):
                maintenance.pair_stage(self.root, stage)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_pair_apply_is_one_shot_and_preserves_home_and_originals(self):
        self.installed_mode()
        (self.root / 'home/history.jsonl').write_bytes(b'complete failed and successful turns\n')
        history = {p.name: p.read_bytes() for p in (self.root / 'home').iterdir()}
        before = (self.root / 'entry.json').read_bytes()
        expected = '1' * 64
        def publisher(root, stage, action, sha=None):
            if action == 'preview':
                return {'preview_sha256': expected}
            self.assertEqual(sha, expected)
            for name in maintenance.PAIR_FILES:
                (root / name).write_bytes((stage / 'staged' / name).read_bytes())
            return {'phase': 'pair_refreshed', 'generation': stage.name}
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(maintenance, 'pair_powershell', side_effect=publisher):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler)['stage'])
            with self.assertRaisesRegex(mode.ModeEntryError, 'preview_changed'):
                maintenance.pair_apply(self.root, stage, '2' * 64)
            self.assertFalse((stage / 'apply-intent.json').exists())
            maintenance.pair_apply(self.root, stage, expected)
            with self.assertRaisesRegex(mode.ModeEntryError, 'stage_not_fresh'):
                maintenance.pair_apply(self.root, stage, expected)
        self.assertEqual((stage / 'originals/entry.json').read_bytes(), before)
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / 'home').iterdir()}, history)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_failed_pair_publish_blocks_launch_without_reset_or_retry(self):
        self.installed_mode()
        with patch.object(mode, 'inspect_package', return_value=self.package):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler)['stage'])
            with patch.object(maintenance, 'pair_powershell', side_effect=[{'preview_sha256': '1' * 64},
                    mode.ModeEntryError('mode_synthetic_publish_failure')]):
                with self.assertRaisesRegex(mode.ModeEntryError, 'synthetic_publish_failure'):
                    maintenance.pair_apply(self.root, stage, '1' * 64)
            with self.assertRaisesRegex(mode.ModeEntryError, 'previous_pair_refresh_uncertain_no_retry'):
                mode.load(self.root)
        self.assertTrue((stage / 'failed.json').is_file())

    def test_only_unchanged_lock_denied_pair_attempt_can_be_retired(self):
        self.installed_mode()
        router = self.root / 'router-launches' / ('c' * 32)
        router.mkdir()
        mode.write_new(router / 'intent.json', {'started_utc': mode.utc()})
        process = {'pid': 15, 'birth': '123', 'executable': 'fixture'}
        mode.write_new(router / 'running.json', {'process': process})
        mode.write_new(router / 'stopped.json', {'process': process, 'server_confirmed_request_free': True})
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'activation_hosts_absent'):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler)['stage'])
            with patch.object(maintenance, 'pair_powershell', side_effect=[{'preview_sha256': '1' * 64},
                    mode.ModeEntryError('mode_pair_entry_busy')]):
                with self.assertRaisesRegex(mode.ModeEntryError, 'entry_busy'):
                    maintenance.pair_apply(self.root, stage, '1' * 64)
            retained = maintenance.unwritten_pair_files(stage)
            preview = maintenance.retire_unwritten_pair(self.root, stage)
            changed = self.project / '.codex/operator-desktop-pair/generations' / stage.name
            changed.mkdir(parents=True)
            with self.assertRaisesRegex(mode.ModeEntryError, 'publication_may_have_started'):
                maintenance.retire_unwritten_pair(self.root, stage, preview['preview_sha256'])
            changed.rmdir()
            maintenance.retire_unwritten_pair(self.root, stage, preview['preview_sha256'])
            self.assertTrue(maintenance.retired_pair_valid(stage))
            self.assertEqual(maintenance.unwritten_pair_files(stage), retained)
            mode.load(self.root)
            with self.assertRaisesRegex(mode.ModeEntryError, 'stage_not_fresh'):
                maintenance.pair_stage(self.root, stage)

    def rolled_back_pair(self):
        self.installed_mode()
        config = self.project / '.codex/operator-desktop-entry/desktop-entry.json'
        value = mode.decode(config.read_bytes())
        value.update(mode_entry_sha256=mode.file_hash(self.root / 'entry.json'), entry_script_sha256='7' * 64)
        config.write_bytes(mode.json_bytes(value))
        with patch.object(mode, 'inspect_package', return_value=self.package):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler)['stage'])
        mode.write_new(stage / 'apply-intent.json', {'preview_sha256': '1' * 64, 'started_utc': mode.utc()})
        mode.write_new(stage / 'failed.json', {'reason': 'mode_pair_refresh_failed', 'automatically_retried': False})
        pair = self.project / '.codex/operator-desktop-pair'
        transaction, generation = pair / 'upgrades' / stage.name, pair / 'generations' / stage.name
        transaction.mkdir(parents=True)
        generation.mkdir(parents=True)
        bundle = config.parent
        for name in ('Codex拓展入口.exe', 'operator_desktop_entry.ps1', 'launcher-manifest.json', 'Codex拓展入口.ico'):
            (bundle / name).write_bytes(('original ' + name).encode())
        link = self.project / 'owned.lnk'
        link.write_bytes(b'owned shortcut unchanged')
        old = {'phase': 'installed', 'scope': 'legacy_entry_only', 'project': str(self.project),
               'home': str(self.native), 'runtime_ownership': 'unresolved', 'generation': '8' * 32,
               'transaction': '8' * 32, 'files': {'native-entry.json': mode.digest(b'original helper')},
               'links': {str(link): {'after': mode.file_hash(link)}},
               'build': {p.name: mode.file_hash(p) for p in bundle.iterdir()},
               'steps': [{'workflow': {'path': str(self.root), 'entry_plan_sha256': mode.file_hash(self.root / 'entry.json')}}]}
        receipt = pair / 'ownership.json'
        mode.write_new(receipt, old)
        manifest = mode.decode(mode.read(stage / 'prepared.json'))
        after_config = {**value, 'mode_entry_sha256': manifest['files']['entry.json']['after']}
        new_build = {**old['build'], 'desktop-entry.json': mode.digest(mode.json_bytes(after_config))}
        workflow = {'contract': mode.CONTRACT, 'path': str(self.root),
                    'entry_plan_sha256': manifest['files']['entry.json']['after'],
                    'entry_script_sha256': value['entry_script_sha256']}
        new = {**old, 'generation': stage.name, 'transaction': stage.name, 'build': new_build,
               'steps': [*old['steps'], {'generation': stage.name, 'before': old['build'],
                                       'after': new_build, 'workflow': workflow}]}
        changes = [(p, p.read_bytes(), mode.json_bytes(after_config) if p == config else p.read_bytes())
                   for p in bundle.iterdir() if p.name != 'Codex拓展入口.ico']
        changes += [(self.root / name, (stage / 'originals' / name).read_bytes(),
                     (stage / 'staged' / name).read_bytes()) for name in maintenance.PAIR_FILES]
        changes += [(receipt, receipt.read_bytes(), mode.json_bytes(new))]
        rows = []
        for i, (path, before, after) in enumerate(changes):
            mode.write_new(transaction / f'{i}.before', before)
            mode.write_new(transaction / f'{i}.after', after)
            rows.append({'path': str(path), 'before': mode.digest(before), 'after': mode.digest(after)})
        mode.write_new(transaction / 'pending.json', {'schema_version': 1, 'phase': 'may_have_written',
                                                     'changes': rows, 'moves': []})
        mode.write_new(generation / 'native-entry.json', b'original helper')
        mode.write_new(generation / 'entry-config.after.json', mode.json_bytes(after_config))
        mode.write_new(generation / 'isolated-entry.after.json', (stage / 'staged/entry.json').read_bytes())
        router = self.root / 'router-launches' / ('c' * 32)
        router.mkdir()
        mode.write_new(router / 'intent.json', {'started_utc': mode.utc()})
        process = {'pid': 15, 'birth': '123', 'executable': 'fixture'}
        mode.write_new(router / 'running.json', {'process': process})
        mode.write_new(router / 'stopped.json', {'process': process, 'server_confirmed_request_free': True})
        return stage, transaction, generation

    def test_rolled_back_pair_review_retains_pending_failure_and_blocks_replay(self):
        stage, transaction, generation = self.rolled_back_pair()
        originals = {p: p.read_bytes() for directory in (stage, transaction, generation)
                     for p in directory.rglob('*') if p.is_file()}
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'activation_hosts_absent'), \
                patch.object(maintenance, 'isolated_processes_absent'):
            preview = maintenance.review_pair_rollback(self.root, stage)
            self.assertFalse((stage / 'retired.json').exists())
            with self.assertRaisesRegex(mode.ModeEntryError, 'preview_changed'):
                maintenance.review_pair_rollback(self.root, stage, '0' * 64)
            maintenance.review_pair_rollback(self.root, stage, preview['preview_sha256'])
            self.assertTrue(maintenance.retired_pair_valid(stage))
            mode.load(self.root)
            with self.assertRaisesRegex(mode.ModeEntryError, 'not_fresh'):
                maintenance.review_pair_rollback(self.root, stage, preview['preview_sha256'])
            with self.assertRaisesRegex(mode.ModeEntryError, 'stage_not_fresh'):
                maintenance.pair_stage(self.root, stage)
        self.assertEqual({p: p.read_bytes() for p in originals}, originals)
        self.assertFalse((transaction / 'completed.json').exists())
        (transaction / '0.before').write_bytes(b'changed original')
        with self.assertRaisesRegex(mode.ModeEntryError, 'backup_changed'):
            maintenance.retired_pair_valid(stage)

    def test_rollback_review_rejects_later_edits_missing_backups_and_running_process(self):
        stage, transaction, generation = self.rolled_back_pair()
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'activation_hosts_absent'), \
                patch.object(maintenance, 'isolated_processes_absent') as absent:
            config = self.root / 'entry.json'
            before = config.read_bytes()
            config.write_bytes(before + b'\n')
            with self.assertRaisesRegex(mode.ModeEntryError, 'baseline_changed'):
                maintenance.review_pair_rollback(self.root, stage)
            self.assertEqual(config.read_bytes(), before + b'\n')
            config.write_bytes(before)
            saved = (transaction / '0.after').read_bytes()
            (transaction / '0.after').unlink()
            with self.assertRaisesRegex(mode.ModeEntryError, 'transaction_invalid'):
                maintenance.review_pair_rollback(self.root, stage)
            mode.write_new(transaction / '0.after', saved)
            absent.side_effect = mode.ModeEntryError('mode_isolated_process_still_running_or_unknown')
            with self.assertRaisesRegex(mode.ModeEntryError, 'still_running'):
                maintenance.review_pair_rollback(self.root, stage)
        self.assertFalse((stage / 'retired.json').exists())
        self.assertFalse((transaction / 'rollback-reviewed.json').exists())

    def test_legacy_reader_accepts_only_complete_retained_rollback_review(self):
        if mode.os.name != 'nt' or not mode.shutil.which('pwsh'):
            self.skipTest('Windows PowerShell required')
        stage, transaction, generation = self.rolled_back_pair()
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'process_matches', return_value=False), \
                patch.object(maintenance, 'activation_hosts_absent'), \
                patch.object(maintenance, 'isolated_processes_absent'):
            preview = maintenance.review_pair_rollback(self.root, stage)
            maintenance.review_pair_rollback(self.root, stage, preview['preview_sha256'])
        program = r'''$ErrorActionPreference='Stop'
$module=Import-Module (Join-Path $env:OPERATOR_TEST_SCRIPTS 'operator_desktop_pair_legacy.psm1') -PassThru -DisableNameChecking
& $module {param($R,$I) Get-LegacyPairTransaction $R $I} $env:OPERATOR_TEST_PAIR $env:OPERATOR_TEST_STAGE | ConvertTo-Json -Compress
'''
        def reader():
            return maintenance.subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', program],
                env={**mode.os.environ, 'OPERATOR_TEST_SCRIPTS': str(mode.SCRIPTS),
                     'OPERATOR_TEST_PAIR': str(transaction.parent.parent), 'OPERATOR_TEST_STAGE': stage.name},
                capture_output=True, text=True, encoding='utf8', timeout=30)
        result = reader()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mode.json.loads(result.stdout)['phase'], 'pair_rollback_reviewed')
        (generation / 'native-entry.json').write_bytes(b'later edit')
        result = reader()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_rollback_review_changed', result.stderr)


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(ModeMaintenanceTests(name) for name in ModeMaintenanceTests.__dict__
                              if name.startswith('test_'))
