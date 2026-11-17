"""Local switch and actual loopback HTTP tests, never against a real Feishu identity."""
import contextlib
import copy
import io
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import test_portable as base
import assistant_control as control
import control_panel as panel
import service
import card_callback_service

class ControlFixture:
    def setUp(self):
        for path in base.rp.ROOT.iterdir():shutil.rmtree(path) if path.is_dir() else path.unlink()
        base.rp.prepare_storage();base.rp.write_state(copy.deepcopy(base.INITIAL))
        self.original=(base.rp.ROOT/'state.json').read_bytes()
    def assert_data_preserved(self):self.assertEqual((base.rp.ROOT/'state.json').read_bytes(),self.original)

class ControlTests(ControlFixture,unittest.TestCase):
    def test_closed_switch_blocks_scan_send_and_extraction_before_auth(self):
        control.set_enabled(False)
        with patch.object(base.collect,'assert_identity') as auth,patch.object(base.collect,'cli_json') as cli:
            with self.assertRaises(control.AssistantDisabled):base.collect.main()
            auth.assert_not_called();cli.assert_not_called()
        with patch.object(base.sender,'cli') as cli:
            with self.assertRaises(control.AssistantDisabled):base.sender.main()
            cli.assert_not_called()
        with patch.object(base.manage,'load') as load:
            with self.assertRaises(control.AssistantDisabled):base.manage.upsert('not-read.json')
            load.assert_not_called()
        self.assert_data_preserved()
    def test_closed_switch_rejects_callbacks_without_writes(self):
        control.set_enabled(False)
        with patch.object(base.callbacks,'cli') as cli:
            self.assertEqual(base.callbacks.process({}),{'ignored':'assistant_disabled'});cli.assert_not_called()
    def test_previous_run_cannot_continue_after_off_then_on(self):
        old=control.require_enabled();control.set_enabled(False);control.set_enabled(True)
        with self.assertRaises(control.AssistantDisabled):control.require_enabled(old)
        generation=control.require_enabled();control.set_enabled(True);self.assertEqual(control.require_enabled(),generation)
        self.assert_data_preserved()
    def test_cancel_interrupts_send_wait(self):
        generation=control.require_enabled()
        with patch.object(control.time,'sleep',side_effect=lambda _:control.set_enabled(False)):
            with self.assertRaises(control.AssistantDisabled):control.guarded_wait(60,generation)
    def test_corrupt_switch_fails_closed(self):
        (control.ROOT/'assistant-control.json').write_text('{bad')
        self.assertFalse(control.read_control()['enabled']);control.set_enabled(True);self.assertTrue(control.read_control()['enabled'])
    def test_enable_failure_leaves_assistant_closed(self):
        control.set_enabled(False)
        with patch.object(service,'install',side_effect=RuntimeError('Authorization unavailable')):
            result=panel.change_enabled(True)
        self.assertFalse(result['ok']);self.assertFalse(control.read_control()['enabled']);self.assert_data_preserved()
    def test_close_works_with_expired_feishu_auth(self):
        with patch.object(service,'assert_identity',side_effect=AssertionError('Stop must not require auth')),patch.object(service,'unload') as unload:
            result=panel.change_enabled(False)
        self.assertTrue(result['ok']);unload.assert_called_once();self.assert_data_preserved()
    def test_open_uninitialized_panel_does_not_enable_or_create_business_state(self):
        (control.ROOT/'state.json').unlink()
        result=panel.get_status();self.assertFalse(result['initialized'])
        with self.assertRaises(ValueError):panel.change_enabled(True)
        self.assertFalse((control.ROOT/'state.json').exists())
    def test_status_contains_no_identifiers_or_credentials(self):
        data=json.dumps(panel.get_status())
        for private in ['ou_OFFLINE','cli_OFFLINE','base_OFFLINE','recipient_open_id','token']:self.assertNotIn(private,data)
        self.assert_data_preserved()
    def test_entry_creation_starts_no_service_and_preserves_data(self):
        with patch.object(service,'deploy',return_value=control.ROOT/'package'),patch.object(panel.subprocess,'Popen') as spawn:
            result=panel.install_entry(control.ROOT/'test-desktop')
        self.assertTrue(pathlib.Path(result['entry']).exists());spawn.assert_not_called();self.assert_data_preserved()
    def test_process_selection_excludes_other_installations(self):
        expected=str(control.ROOT/'package/scripts/card_callback_service.py')
        table={100:{'ppid':1,'command':'python '+expected},101:{'ppid':100,'command':'lark-cli event consume'},
               200:{'ppid':1,'command':'python /another-installation/card_callback_service.py'},201:{'ppid':200,'command':'lark-cli event consume'}}
        self.assertEqual(set(service.receiver_processes(table)),{100,101})
    def test_reused_pid_is_not_terminated(self):
        with patch.object(service,'process_table',return_value={123:{'command':'unrelated application','ppid':1}}),patch.object(service.os,'kill') as kill:
            service.terminate_owned({123:{'command':'old receiver','ppid':1}})
        kill.assert_not_called()
    @unittest.skipIf(os.name=='nt','POSIX process group behavior')
    def test_group_cleanup_continues_when_wrapper_has_exited(self):
        from unittest.mock import Mock
        child=Mock(pid=987654);child.poll.return_value=0
        with patch.object(card_callback_service.os,'killpg') as terminate:
            card_callback_service.terminate_consumer(child)
        terminate.assert_called_with(child.pid,signal.SIGTERM)
    def test_new_initialization_is_closed_and_has_entry(self):
        fake=base.FakeBase()
        with patch.object(base.rp,'cli_json',return_value={'identities':{'user':{'status':'ready','available':True,'openId':base.IDENTITY['recipient_open_id']}},'appId':base.IDENTITY['application_id']}),patch.object(base.ds,'call',side_effect=fake.call),patch.object(base.ds,'rows',side_effect=fake.rows),patch.object(panel,'install_entry',return_value={'entry_created':True,'entry':'TEST_ENTRY'}),contextlib.redirect_stdout(io.StringIO()):
            base.manage.init(True)
            self.assertFalse(control.read_control()['enabled'])
            self.assertTrue(panel.read(control.ROOT/'state.json')['control_entry']['entry_created'])
            control.set_enabled(True);base.manage.init(True)
            self.assertTrue(control.read_control()['enabled'])

class HttpControlTests(ControlFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.server=panel.create_server()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
    def request(self,path='/api/status',value=None,token=True,origin=None,host=None):
        headers={}
        if token:headers['X-Control-Token']=self.server.token
        if origin:headers['Origin']=origin
        if host:headers['Host']=host
        data=None
        if value is not None:data=json.dumps(value).encode();headers['Content-Type']='application/json'
        return urllib.request.urlopen(urllib.request.Request(self.server.origin+path,data=data,headers=headers),timeout=10)
    def test_http_switch_is_real_and_preserves_business_state(self):
        control.set_enabled(False)
        with patch.object(service,'install',return_value={}) as start,patch.object(service,'stop',side_effect=lambda _:control.set_enabled(False)) as stop:
            with self.request('/api/control',{'enabled':True}) as response:self.assertTrue(json.load(response)['status']['enabled'])
            with self.request('/api/control',{'enabled':False}) as response:self.assertFalse(json.load(response)['status']['enabled'])
        start.assert_called_once();stop.assert_called_once();self.assert_data_preserved()
    def test_missing_token_and_cross_origin_cannot_toggle(self):
        with patch.object(panel,'change_enabled') as change:
            for kwargs in [{'token':False},{'origin':'https://untrusted.invalid'},{'host':'untrusted.invalid'}]:
                with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/control',{'enabled':False},**kwargs)
                self.assertEqual(error.exception.code,403)
            change.assert_not_called()
    def test_invalid_controls_are_rejected(self):
        for value in [{'enabled':'false'},{'enabled':0},{'enabled':True,'recipient':'other'}]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/control',value)
            self.assertEqual(error.exception.code,400)
        self.assert_data_preserved()
    def test_page_is_self_contained_and_get_cannot_change_state(self):
        with self.request('/',token=False) as response:
            html=response.read().decode();self.assertIn('开启助手',html);self.assertIn('关闭助手',html)
            self.assertNotIn('src="http',html);self.assertIn('frame-ancestors',response.headers['Content-Security-Policy'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/control?enabled=false')
        self.assertTrue(control.read_control()['enabled'])
    def test_double_click_reuses_existing_local_server(self):
        descriptor={'pid':os.getpid(),'url':self.server.origin,'token':self.server.token,'runtime':str(control.ROOT)}
        (control.ROOT/'control-server.json').write_text(json.dumps(descriptor))
        with patch.object(panel.subprocess,'Popen') as spawn,contextlib.redirect_stdout(io.StringIO()):url=panel.open_panel(no_browser=True)
        self.assertTrue(url.startswith(self.server.origin));spawn.assert_not_called()

class ReceiverCleanupTests(ControlFixture,unittest.TestCase):
    def start_receiver(self):
        script=control.ROOT/'fake-event.py'
        script.write_text("import os,pathlib,sys,time\npathlib.Path('fake-consumer.pid').write_text(str(os.getpid()))\nprint('[event] ready event_key=card.action.trigger',file=sys.stderr,flush=True)\nwhile True:time.sleep(0.1)\n")
        harness="import sys;sys.path.insert(0,sys.argv[1]);import card_callback_service as s;s.CLI_ARGS=[sys.executable,sys.argv[2]];s.main()"
        child=subprocess.Popen([sys.executable,'-B','-c',harness,str(base.PACKAGE/'scripts'),str(script)],cwd=control.ROOT,
            env=dict(os.environ,FEISHU_TODO_HOME=str(control.ROOT)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        def cleanup():
            if child.poll() is None:child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            child.stderr.close()
        self.addCleanup(cleanup)
        for _ in range(80):
            state=panel.read(control.ROOT/'card-service-status.json',{})
            if state.get('ready'):return child,state['consumer_pid']
            if child.poll() is not None:self.fail(child.stderr.read())
            time.sleep(0.05)
        self.fail('Fake consumer did not become ready')
    def test_switch_off_disconnects_idle_consumer(self):
        child,pid=self.start_receiver();control.set_enabled(False);child.wait(timeout=5)
        self.assertFalse(panel.read(control.ROOT/'card-service-status.json')['ready'])
        with self.assertRaises(OSError):os.kill(pid,0)
        self.assert_data_preserved()
    def test_sigterm_disconnects_consumer(self):
        child,pid=self.start_receiver();child.terminate();child.wait(timeout=5)
        with self.assertRaises(OSError):os.kill(pid,0)

if __name__=='__main__':unittest.main(verbosity=2)
