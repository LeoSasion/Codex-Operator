"""No real windows or live handoffs: test the status/defer boundary in isolation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from operator_handoff_feedback import Feedback, FeedbackError, read_state

SHELL = Path(os.environ.get('ProgramFiles','')) / 'PowerShell/7/pwsh.exe'
SCRIPT = Path(__file__).resolve().parents[3] / 'scripts/operator_handoff_status.ps1'


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-feedback-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.feedback = Feedback(self.root, 'a' * 64, 120)
        self.feedback.process = Mock(pid=123)
        self.feedback.process.poll.return_value = None

    def state(self):
        return read_state(self.root)

    def test_waiting_is_visible_and_only_exact_session_can_defer(self):
        self.feedback.deadline = 1120
        with patch('operator_handoff_feedback.time.monotonic', return_value=1000):
            self.feedback.waiting()
        self.assertEqual(self.state()['remaining_seconds'],120)
        cancel = self.root/'defer.json'
        cancel.write_text(json.dumps({'schema_version':1,'session':'b'*64}))
        with self.assertRaisesRegex(FeedbackError,'record_invalid'):
            self.feedback.applying()
        self.assertEqual(self.state()['phase'],'waiting')
        cancel.write_text(json.dumps({'schema_version':1,'session':'a'*64}))
        with self.assertRaisesRegex(FeedbackError,'handoff_deferred'):
            self.feedback.applying()
        self.assertEqual(self.state()['phase'],'waiting')

    def test_closed_window_blocks_before_maintenance(self):
        self.feedback.process.poll.return_value = 0
        with self.assertRaisesRegex(FeedbackError,'feedback_closed'):
            self.feedback.applying()
        self.assertFalse((self.root/'feedback.jsonl').exists())

    def test_final_outcome_never_equates_attempted_reopen_with_success(self):
        result={'status':'stopped_for_review','stage':'activate_official',
                'native_reopen_attempted':True,'native_reopen_witnessed':False}
        self.feedback.finish(result)
        self.assertEqual(self.state()['outcome'],'review_required')
        self.feedback.finish({**result,'native_reopen_witnessed':True})
        self.assertEqual(self.state()['outcome'],'native_recovered')
        self.feedback.finish({'status':'config_switch_witnessed'})
        self.assertEqual(self.state()['outcome'],'complete')

    def test_window_ready_requires_matching_identity_before_waiting(self):
        (self.root/'feedback-ready.json').write_text(json.dumps(
            {'schema_version':1,'session':'a'*64,'pid':123}))
        with patch('operator_handoff_feedback.subprocess.Popen', return_value=self.feedback.process) as launch:
            self.feedback.start()
        self.assertEqual(self.state()['phase'],'waiting')
        self.assertIn('-STA',launch.call_args.args[0])
        self.assertIn('Hidden',launch.call_args.args[0])
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_ack_from_another_window_does_not_start_waiting(self):
        (self.root/'feedback-ready.json').write_text(json.dumps(
            {'schema_version':1,'session':'b'*64,'pid':123}))
        with patch('operator_handoff_feedback.subprocess.Popen', return_value=self.feedback.process):
            with self.assertRaisesRegex(FeedbackError,'ready_changed'):
                self.feedback.start()

    @unittest.skipUnless(os.name == 'nt' and SHELL.is_file(), 'Windows Forms and PowerShell required')
    def test_windows_reader_keeps_complete_snapshots_during_live_updates(self):
        self.feedback.publish('waiting')
        driver = self.root/'reader.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n. " + quote(SCRIPT) +
            ' -RunDirectory '+quote(self.root)+' -Session '+quote('a'*64)+' -Library\n' +
            "[IO.File]::WriteAllText((Join-Path $root 'reader-ready'),'ready')\n"+
            "$watch=[Diagnostics.Stopwatch]::StartNew();$reads=0\n"+
            "while ($watch.Elapsed.TotalSeconds -lt 5) { $v=Read-Status;"+
            "if ($v.session -cne $Session) {throw 'changed snapshot'};$reads++ }\n"+
            "[Console]::WriteLine($reads);$form.Dispose();$timer.Dispose()\n",encoding='utf8')
        child = subprocess.Popen([str(SHELL),'-NoProfile','-STA','-File',str(driver)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+10
            while not (self.root/'reader-ready').exists():
                self.assertIsNone(child.poll())
                self.assertLess(time.monotonic(),deadline)
                time.sleep(.02)
            for _ in range(300):
                self.feedback.publish('waiting',remaining=60)
            output,error=child.communicate(timeout=12)
            self.assertEqual(child.returncode,0,error.decode('utf8','replace'))
            self.assertGreater(int(output.strip()),10)
        finally:
            if child.poll() is None:
                child.kill();child.communicate(timeout=5)

    def test_partial_tail_and_oversized_journal_cannot_claim_completion(self):
        self.feedback.publish('waiting',remaining=30)
        path=self.root/'feedback.jsonl'
        with path.open('ab') as stream:
            stream.write(b'{"phase":"finished"')
        self.assertEqual(self.state()['phase'],'waiting')
        path.write_bytes(b' '*(512*1024))
        with self.assertRaisesRegex(FeedbackError,'state_bound'):
            self.feedback.publish('finished')

    @unittest.skipUnless(os.name == 'nt' and SHELL.is_file(), 'Windows Forms and PowerShell required')
    def test_forms_defer_button_and_terminal_display(self):
        self.feedback.publish('waiting',remaining=60)
        driver=self.root/'controls.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n. "+quote(SCRIPT)+
            ' -RunDirectory '+quote(self.root)+' -Session '+quote('a'*64)+' -Preview -Library\n'+r'''
$form.ShowInTaskbar=$false
$form.StartPosition='Manual'
$form.Location=[Drawing.Point]::new(-10000,-10000)
$form.Show();$timer.Start()
$watch=[Diagnostics.Stopwatch]::StartNew()
while ($watch.Elapsed.TotalSeconds -lt 1) {[Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 20}
if ($title.Text -cne '等待 Codex 完全退出' -or -not $button.Enabled) {throw 'Waiting controls unavailable'}
$button.PerformClick()
if (-not $script:deferred -or $button.Enabled) {throw 'Defer was not requested'}
$saved=Get-Content (Join-Path $root 'defer.json') -Raw | ConvertFrom-Json
if ($saved.session -cne $Session) {throw 'Wrong defer identity'}
Show-Terminal 'deferred'
if ($title.Text -cne '本次暂不升级' -or $button.Text -cne '关闭' -or -not $button.Enabled) {throw 'Final controls unavailable'}
$timer.Stop();$form.Close();$form.Dispose();$timer.Dispose()
[Console]::WriteLine('controls_passed')
''',encoding='utf8')
        result=subprocess.run([str(SHELL),'-NoProfile','-STA','-File',str(driver)],
            capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf8','replace'))
        self.assertEqual(result.stdout.strip(),b'controls_passed')


if __name__ == '__main__':
    unittest.main()
