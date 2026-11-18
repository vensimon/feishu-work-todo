"""Dialog-driven lifecycle tests; use isolated data and no real Feishu account."""
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
import time
import unittest
from unittest.mock import patch
import test_portable as base
import assistant_control as control
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
            with self.assertRaises(RuntimeError):service.resume(base.INITIAL)
        self.assertFalse(control.read_control()['enabled']);self.assert_data_preserved()
    def test_close_works_with_expired_feishu_auth(self):
        with patch.object(service,'assert_identity',side_effect=AssertionError('Stop must not require auth')),patch.object(service,'unload') as unload:
            result=service.stop(base.INITIAL)
        self.assertTrue(result['receiver_stopped']);unload.assert_called_once();self.assert_data_preserved()
    def test_status_requires_no_auth_and_creates_no_entry(self):
        with patch.object(service,'assert_identity',side_effect=AssertionError('Status is read-only')),patch.object(service.subprocess,'Popen') as spawn:
            self.assertTrue(service.status()['initialized']);spawn.assert_not_called()
        self.assert_data_preserved()
    def test_uninitialized_resume_is_rejected_without_enabling(self):
        (control.ROOT/'state.json').unlink();control.set_enabled(False)
        with self.assertRaises(ValueError):service.resume({})
        self.assertFalse(control.read_control()['enabled'])
        self.assertFalse((control.ROOT/'state.json').exists())
    def test_resume_and_pause_cli_preserve_all_records(self):
        control.set_enabled(False)
        with patch.object(service,'install',return_value={'receiver_started':True}) as start,patch.object(service,'unload') as stop,contextlib.redirect_stdout(io.StringIO()):
            with patch.object(sys,'argv',['service.py','resume','--confirm']):service.main()
            self.assertTrue(control.read_control()['enabled'])
            with patch.object(sys,'argv',['service.py','pause','--confirm']):service.main()
            self.assertFalse(control.read_control()['enabled'])
        start.assert_called_once();stop.assert_called_once();self.assert_data_preserved()
    def test_mutation_requires_explicit_action(self):
        with patch.object(service,'resume') as start,patch.object(service,'stop') as stop:
            with patch.object(sys,'argv',['service.py','pause']):
                with self.assertRaises(RuntimeError):service.main()
            start.assert_not_called();stop.assert_not_called()
        self.assert_data_preserved()
    def test_resume_is_idempotent_when_current_receiver_is_connected(self):
        with patch.object(service,'status',return_value={'enabled':True,'receiver_connected':True,'receiver_version':service.CLIENT_VERSION}),patch.object(service,'install') as install:
            self.assertTrue(service.resume(base.INITIAL)['already_running']);install.assert_not_called()
        self.assert_data_preserved()
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
    def test_new_initialization_is_paused_without_entry_or_receiver(self):
        fake=base.FakeBase()
        with patch.object(base.rp,'cli_json',return_value={'identities':{'user':{'status':'ready','available':True,'openId':base.IDENTITY['recipient_open_id']}},'appId':base.IDENTITY['application_id']}),patch.object(base.ds,'call',side_effect=fake.call),patch.object(base.ds,'rows',side_effect=fake.rows),patch.object(service,'install') as start,contextlib.redirect_stdout(io.StringIO()):
            base.manage.init(True)
            self.assertFalse(control.read_control()['enabled'])
            self.assertNotIn('control_entry',json.loads((control.ROOT/'state.json').read_text()))
            start.assert_not_called()
            control.set_enabled(True);base.manage.init(True)
            self.assertTrue(control.read_control()['enabled'])

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
            state=service.read(control.ROOT/'card-service-status.json',{})
            if state.get('ready'):return child,state['consumer_pid']
            if child.poll() is not None:self.fail(child.stderr.read())
            time.sleep(0.05)
        self.fail('Fake consumer did not become ready')
    def test_switch_off_disconnects_idle_consumer(self):
        child,pid=self.start_receiver();control.set_enabled(False);child.wait(timeout=5)
        self.assertFalse(service.read(control.ROOT/'card-service-status.json')['ready'])
        with self.assertRaises(OSError):os.kill(pid,0)
        self.assert_data_preserved()
    def test_sigterm_disconnects_consumer(self):
        child,pid=self.start_receiver();child.terminate();child.wait(timeout=5)
        with self.assertRaises(OSError):os.kill(pid,0)

if __name__=='__main__':unittest.main(verbosity=2)
