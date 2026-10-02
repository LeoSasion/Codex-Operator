"""Desktop links/recovery in disposable directories; never launch the real app."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[2]/'scripts'
PWSH=shutil.which('pwsh')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def q(value):
    return "'"+str(value).replace("'","''")+"'"


@unittest.skipUnless(os.name=='nt' and PWSH,'Windows PowerShell required')
class DesktopPairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='operator-pair-')
        self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name).resolve()
        self.desktop=self.project/'desktop';self.desktop.mkdir()
        self.home=self.project/'home';self.home.mkdir()
        self.bundle=self.project/'.codex/operator-desktop-entry';self.bundle.mkdir(parents=True)
        self.root=self.project/'.codex/operator-desktop-pair'
        self.binary=b'synthetic never executed'
        self.entry=b'synthetic installed entry'
        (self.bundle/'Codex拓展入口.exe').write_bytes(self.binary)
        (self.bundle/'operator_desktop_entry.ps1').write_bytes(self.entry)
        self.metadata={'schema_version':1,'native_fallback':'native-only-v1',
            'binary_sha256':digest(self.binary),'entry_script_sha256':digest(self.entry),
            'build_date':'2026-09-30','product_version':'1.2.0-preview.1','source_sha256':'a'*64}
        self.write_build()
        (self.bundle/'desktop-entry.json').write_text(json.dumps({'schema_version':1,'mode':'native',
            'entry_script_sha256':digest(self.entry)}),encoding='utf8')
        owner=self.project/'.codex/operator-installation/ownership.json'
        owner.parent.mkdir();owner.write_text(json.dumps({'schema_version':1,'project':str(self.project),'entries':{}}))
        self.args=(f'-ProjectRoot {q(self.project)} -CodexHome {q(self.home)} -DesktopDirectory {q(self.desktop)} '
            "-BuildDate '2026-09-30' -Version '1.2.0-preview.1' -SourceDigest "+q('a'*64))

    def write_build(self):
        (self.bundle/'launcher-manifest.json').write_text(json.dumps(self.metadata),encoding='utf8')

    def ps(self,code,*,imports=True,env=None,default_home=True):
        driver=self.project/'driver.ps1'
        prefix="$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
        if imports:
            prefix+='Import-Module '+q(SCRIPTS/'operator_desktop_pair.psm1')+' -Force -DisableNameChecking\n'
            if default_home:
                prefix+='& (Get-Module operator_desktop_pair) { function script:Get-OperatorPairDefaultHome {return '+q(self.home)+'} }\n'
        driver.write_text(prefix+code,encoding='utf8')
        return subprocess.run([PWSH,'-NoProfile','-File',str(driver)],capture_output=True,text=True,
            encoding='utf8',timeout=30,env=env or {**os.environ,'CODEX_HOME':str(self.home)},creationflags=subprocess.CREATE_NO_WINDOW)

    def install(self):
        result=self.ps('Install-OperatorDesktopPair '+self.args+' | ConvertTo-Json -Compress')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result

    def links(self):
        return {p.name:p.read_bytes() for p in self.desktop.glob('*.lnk')}

    def test_install_two_dated_links_reuse_and_restore_retains_native_helpers(self):
        result=self.install()
        self.assertTrue(json.loads(result.stdout)['changed'])
        original=self.links()
        self.assertEqual(set(original),{'ChatGPT 原生入口.lnk','ChatGPT 拓展模型 09-30 入口.lnk'})
        receipt=json.loads((self.root/'ownership.json').read_text())
        self.assertEqual(receipt['build_date'],'2026-09-30')
        self.assertEqual(receipt['source_sha256'],'a'*64)
        self.assertFalse(json.loads(self.install().stdout)['changed'])
        self.assertEqual(self.links(),original)
        restored=self.ps('Restore-OperatorDesktopPair -ProjectRoot '+q(self.project)+' | ConvertTo-Json -Compress')
        self.assertEqual(restored.returncode,0,restored.stderr)
        self.assertEqual(self.links(),{})
        self.assertTrue((self.root/'generations'/receipt['generation']/'operator_native_entry.ps1').is_file())
        self.assertEqual(len(list((self.root/'transactions').glob('*/ownership.before.json'))),1)
        self.assertFalse((self.root/'pending.json').exists())

    def test_reject_wrong_build_metadata_and_pending_activation_without_writes(self):
        for args in (self.args.replace('2026-09-30','2026-10-01'),self.args.replace('1.2.0-preview.1','2.0.0'),
                     self.args.replace('a'*64,'b'*64)):
            result=self.ps('Install-OperatorDesktopPair '+args)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('pair_build_metadata_mismatch',result.stderr)
            self.assertFalse(self.root.exists())
        (self.home/'operator-unified-activation').mkdir()
        result=self.ps('Install-OperatorDesktopPair '+self.args)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('pair_activation_requires_separate_review',result.stderr)
        self.assertFalse(self.root.exists())

    def test_existing_shortcut_and_entry_only_install_are_not_adopted(self):
        target=self.desktop/'ChatGPT 原生入口.lnk';target.write_bytes(b'user owned')
        result=self.ps('Install-OperatorDesktopPair '+self.args)
        self.assertIn('pair_shortcut_name_conflict',result.stderr)
        self.assertEqual(target.read_bytes(),b'user owned')
        target.unlink()
        (self.project/'.codex/operator-installation/ownership.json').unlink()
        result=self.ps('Install-OperatorDesktopPair '+self.args)
        self.assertIn('pair_legacy_migration_required',result.stderr)
        self.assertFalse(self.root.exists())

    def test_later_edits_and_changed_build_preserve_pair(self):
        self.install()
        target=self.desktop/'ChatGPT 原生入口.lnk'
        target.write_bytes(b'later user edit')
        for command in ('Install-OperatorDesktopPair '+self.args,'Restore-OperatorDesktopPair -ProjectRoot '+q(self.project)):
            result=self.ps(command)
            self.assertIn('pair_shortcut_changed',result.stderr)
            self.assertEqual(target.read_bytes(),b'later user edit')

    def test_changed_successful_build_requires_review_and_retains_previous_date(self):
        self.install()
        links=self.links()
        receipt=(self.root/'ownership.json').read_bytes()
        self.metadata['build_date']='2026-10-01';self.write_build()
        result=self.ps('Install-OperatorDesktopPair '+self.args.replace('2026-09-30','2026-10-01'))
        self.assertIn('pair_extension_build_changed',result.stderr)
        self.assertEqual(self.links(),links)
        self.assertEqual((self.root/'ownership.json').read_bytes(),receipt)

    def test_failed_second_link_rolls_back_first_and_retains_terminal_intent(self):
        # Inject a local filesystem failure exactly at the second public write.
        code=r'''
$module=Get-Module operator_desktop_pair
& $module {
    $script:realWrite=(Get-Command Write-RecoveryChange).ScriptBlock
    function script:Write-RecoveryChange($Change) {
        if ($Change.path -like '*ChatGPT 拓展模型*.lnk') {throw 'synthetic_write_failure'}
        & $script:realWrite $Change
    }
}
'''+ 'Install-OperatorDesktopPair '+self.args
        result=self.ps(code)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.links(),{})
        self.assertTrue((self.root/'pending.json').is_file())
        again=self.ps('Install-OperatorDesktopPair '+self.args)
        self.assertIn('pair_pending_requires_review',again.stderr)
        self.assertEqual(self.links(),{})

    def test_activation_created_during_shortcut_preparation_blocks_publication(self):
        code=r'''
$module=Get-Module operator_desktop_pair
& $module {
    $script:realShortcut=(Get-Command New-OperatorPairShortcut).ScriptBlock
    function script:New-OperatorPairShortcut($Path,$Target,$Arguments,$WorkingDirectory,$Description) {
        $bytes=& $script:realShortcut $Path $Target $Arguments $WorkingDirectory $Description
        [void][IO.Directory]::CreateDirectory('''+q(self.home/'operator-unified-activation')+r''')
        return ,$bytes
    }
}
'''+ 'Install-OperatorDesktopPair '+self.args
        result=self.ps(code)
        self.assertIn('pair_activation_requires_separate_review',result.stderr)
        self.assertEqual(self.links(),{})
        self.assertFalse((self.root/'ownership.json').exists())

    def test_module_import_preserves_installers_arguments(self):
        result=self.ps("$ProjectRoot='keep-project';$CodexHome='keep-home';$Apply=$true;$CheckOnly=$true\nImport-Module "+
            q(SCRIPTS/'operator_desktop_pair.psm1')+" -Force -DisableNameChecking\n"+
            "@($ProjectRoot,$CodexHome,$Apply,$CheckOnly) | ConvertTo-Json -Compress",imports=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),['keep-project','keep-home',True,True])

    def test_native_real_recovery_needs_exit_then_preserves_original_before_launch(self):
        # The real recovery parser/backup/write code sees a disposable recognized route.
        config=self.home/'config.toml'
        config.write_text('# BEGIN FEISHU OPERATOR MODEL ROUTER\nopenai_base_url = "http://127.0.0.1:4317/'+('a'*64)+'/v1"\n# END FEISHU OPERATOR MODEL ROUTER\nmodel = "fixture"\n',encoding='utf8')
        original=config.read_bytes()
        code='. '+q(SCRIPTS/'restore-codex-official-route.ps1')+' -Library\n. '+q(SCRIPTS/'operator_native_entry.ps1')+' -Library\n'+r'''
function Get-OperatorNativeDefaultHome {return '''+q(self.home)+r'''}
function Get-OperatorPackagedApplication {return @{aumid='synthetic'}}
function Open-OperatorPackagedApplication {param($App);$script:launches++}
$script:launches=0
function Get-CimInstance {return @([pscustomobject]@{Name='ChatGPT.exe';CreationDate=[DateTime]::UtcNow})}
'''+ '$a=Invoke-OperatorNativeEntry '+q(self.project)+' '+q(self.home)+r'''
if ($a.status -ne 'normal_exit_required' -or $script:launches) {throw 'running recovery boundary'}
function Get-CimInstance {return @()}
'''+ '$b=Invoke-OperatorNativeEntry '+q(self.project)+' '+q(self.home)+r'''
@{first=$a;second=$b;launches=$script:launches}|ConvertTo-Json -Depth 5 -Compress
'''
        result=self.ps(code,imports=False,env={**os.environ,'CODEX_HOME':str(self.home),'OPENAI_BASE_URL':''})
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['second']['status'],'launch_requested')
        self.assertTrue(value['second']['configuration_changed'])
        self.assertEqual(value['launches'],1)
        self.assertEqual(config.read_text(),'model = "fixture"\n')
        backups=list((self.home/'operator-route-recovery').glob('*/config.toml.before'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),original)

    def test_native_script_check_only_does_not_lose_flag_when_loading_helpers(self):
        folder=self.project/'native-fixture';folder.mkdir()
        shutil.copyfile(SCRIPTS/'operator_native_entry.ps1',folder/'operator_native_entry.ps1')
        recovery=b'''param([string]$CodexHome,[string]$ProjectRoot,[switch]$Apply,[switch]$Json,[switch]$Library)
function Invoke-OfficialRouteRecovery($HomePath,$Project,$Commit) {
if ($Commit) {throw 'unexpected recovery'}
return @{status='preview';route_before='operator';warnings=@();config_changed=$false}
}
function Get-CimInstance {return @()}
'''
        entry=('''param([string]$StartupBundle,[switch]$CheckOnly,[switch]$Library)
function Get-OperatorNativeDefaultHome {return '''+q(self.home)+'''}
function Get-OperatorPackagedApplication {return @{aumid='synthetic'}}
function Open-OperatorPackagedApplication {throw 'unexpected launch'}
''').encode('utf8')
        for name,data in [('restore-codex-official-route.ps1',recovery),('operator_desktop_entry.ps1',entry)]:
            (folder/name).write_bytes(data)
        (folder/'native-entry.json').write_text(json.dumps({'schema_version':1,'project':str(self.project),
            'home':str(self.home),'files':{'restore-codex-official-route.ps1':digest(recovery),
            'operator_desktop_entry.ps1':digest(entry)}}))
        result=subprocess.run([PWSH,'-NoProfile','-File',str(folder/'operator_native_entry.ps1'),'-CheckOnly'],
            capture_output=True,text=True,encoding='utf8',timeout=20,env={**os.environ,'CODEX_HOME':str(self.home)},
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'],'recover_then_open')
        self.assertFalse(json.loads(result.stdout)['configuration_changed'])
        self.assertFalse((self.home/'operator-native-route-only').exists())

    def test_native_home_mismatch_old_running_route_and_launch_failure_stay_distinct(self):
        (self.home/'config.toml').write_text('model = "fixture"\n')
        code='. '+q(SCRIPTS/'operator_native_entry.ps1')+' -Library\n'+r'''
function Get-OperatorNativeDefaultHome {return '''+q(self.home)+r'''}
$script:commits=0;$script:launches=0
function Invoke-OfficialRouteRecovery($HomePath,$Project,$Commit) {
    if ($Commit) {$script:commits++;return @{status='completed';warnings=@();config_changed=$true}}
    return @{status='preview';route_before='native';warnings=@()}
}
function Get-OperatorPackagedApplication {return @{aumid='synthetic'}}
function Open-OperatorPackagedApplication {$script:launches++;throw 'synthetic failed launch'}
function Get-CimInstance {return @([pscustomobject]@{CreationDate=[DateTime]::UtcNow.AddHours(-1)})}
'''+ '$old=Invoke-OperatorNativeEntry '+q(self.project)+' '+q(self.home)+r'''
function Get-CimInstance {return @()}
'''+ '$mismatch=Invoke-OperatorNativeEntry '+q(self.project)+' '+q(self.project/'different-home')+'\n'+ \
            '$failed=Invoke-OperatorNativeEntry '+q(self.project)+' '+q(self.home)+r'''
@{old=$old;mismatch=$mismatch;failed=$failed;commits=$script:commits;launches=$script:launches}|ConvertTo-Json -Depth 5 -Compress
'''
        result=self.ps(code,imports=False,env={**os.environ,'CODEX_HOME':str(self.home)})
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['old']['status'],'normal_exit_required')
        self.assertEqual(value['mismatch']['status'],'needs_review')
        self.assertEqual(value['failed']['status'],'launch_failed')
        self.assertEqual(value['commits'],0)
        self.assertEqual(value['launches'],1)

    def test_nondefault_home_rejects_install_and_native_before_any_recovery(self):
        result=self.ps('Install-OperatorDesktopPair '+self.args,default_home=False)
        self.assertIn('pair_default_home_required',result.stderr)
        self.assertFalse(self.root.exists())
        code='. '+q(SCRIPTS/'operator_native_entry.ps1')+' -Library\n'+r'''
function Invoke-OfficialRouteRecovery {throw 'unexpected recovery'}
function Get-OperatorPackagedApplication {throw 'unexpected package lookup'}
function Open-OperatorPackagedApplication {throw 'unexpected launch'}
'''+ 'Invoke-OperatorNativeEntry '+q(self.project)+' '+q(self.home)+' | ConvertTo-Json -Compress'
        native=self.ps(code,imports=False,env={**os.environ,'CODEX_HOME':str(self.home)})
        self.assertEqual(native.returncode,0,native.stderr)
        self.assertEqual(json.loads(native.stdout),{'status':'needs_review','configuration_changed':False,'launch_requested':False})
        self.assertFalse((self.home/'operator-native-route-only').exists())


if __name__=='__main__':
    unittest.main()
