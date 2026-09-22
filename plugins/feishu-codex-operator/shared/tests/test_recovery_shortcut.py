"""Owned recovery shortcuts in disposable desktops, no real route activation."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=_OPERATOR_PLUGIN_ROOT/'scripts'
sys.path.insert(0,str(SCRIPTS))
from operator_core import model_router_config as config
from operator_core.model_registry import RouterError
PS=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'


@unittest.skipUnless(os.name=='nt' and PS.exists(),'Windows shortcut COM required')
class RecoveryShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='s-')
        self.addCleanup(self.temp.cleanup)
        # Windows may expose TEMP through an 8.3 alias while WScript returns
        # the existing directory's long path. Bind the fixture to that same path.
        self.root=Path(self.temp.name).resolve(strict=True)
        self.desktop=self.root/'desktop'; self.desktop.mkdir()
        self.bundle=self.root/'.codex/operator-native-recovery'
        self.link=self.desktop/'恢复官方默认路由.lnk'

    def install(self):
        p=subprocess.run([str(PS),'-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(SCRIPTS/'install-native-recovery-shortcut.ps1'),'-ProjectRoot',str(self.root),
            '-DesktopDirectory',str(self.desktop)],capture_output=True,timeout=30)
        return p.returncode,json.loads(p.stdout)

    def test_create_repeat_repair_and_preserve_user_change(self):
        code,result=self.install()
        self.assertEqual(code,0,result)
        self.assertTrue(result['changed'])
        self.assertEqual(Path(result['shortcut']),self.link)
        for name in ('恢复官方默认路由.cmd','restore-codex-official-route.ps1'):
            self.assertEqual((self.bundle/name).read_bytes(),(SCRIPTS/name).read_bytes())
        before=self.link.read_bytes()
        self.assertFalse(self.install()[1]['changed'])
        self.assertEqual(before,self.link.read_bytes())
        self.link.unlink()
        self.assertEqual(self.install()[0],0)
        # User changes must stop setup, not be silently replaced by an upgrade.
        modified=b'user changed shortcut'
        self.link.write_bytes(modified)
        self.assertEqual(self.install()[0],1)
        self.assertEqual(self.link.read_bytes(),modified)

    def test_unowned_name_collision_prevents_adoption(self):
        self.link.write_bytes(b'belongs to someone else')
        self.assertEqual(self.install()[0],1)
        self.assertEqual(self.link.read_bytes(),b'belongs to someone else')
        self.assertFalse(self.bundle.exists())

    def test_global_activation_requires_shortcut_before_health(self):
        home=self.root/'.codex'; home.mkdir()
        target=home/'config.toml'; target.write_bytes(b'model="native"\n')
        config.initialize(self.root/'state')
        response=subprocess.CompletedProcess([],1,stdout=b'{"status":"stopped"}')
        with patch.object(Path,'home',return_value=self.root), patch('subprocess.run',return_value=response) as run, patch.object(config,'health') as health:
            with self.assertRaisesRegex(RouterError,'recovery_shortcut_required'):
                config.activate(self.root/'state',4317,target)
            run.assert_called_once()
            health.assert_not_called()
        self.assertEqual(target.read_bytes(),b'model="native"\n')
        # Private configuration remains side-effect free on the user's desktop.
        with patch('subprocess.run') as run:
            config.ensure_recovery_shortcut(self.root/'fixture/config.toml')
            run.assert_not_called()


if __name__=='__main__': unittest.main()
