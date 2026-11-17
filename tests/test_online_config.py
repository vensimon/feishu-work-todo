"""Exercise actual JSON download parsing and runtime integration without external access."""
import base64
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
import test_portable as base
import online_config as online
import render_batch_card as render

class Response:
    def __init__(self,config,etag='"offline-etag"',api=False):
        self.headers={'ETag':etag}
        self.content=json.dumps(config,ensure_ascii=False).encode()
        self.api=api
    def read(self,limit):
        if not self.api:return self.content[:limit]
        return json.dumps({'type':'file','encoding':'base64','sha':hashlib.sha1(self.content).hexdigest(),
                           'content':base64.b64encode(self.content).decode(),
                           'download_url':'https://example.invalid/not-used'}).encode()[:limit]
    def __enter__(self):return self
    def __exit__(self,*args):pass

class OnlineTests(unittest.TestCase):
    def setUp(self):
        for path in online.ROOT.iterdir():shutil.rmtree(path) if path.is_dir() else path.unlink()
        online.prepare_storage()
        self.assets=tempfile.TemporaryDirectory(prefix='todo-assets-');self.addCleanup(self.assets.cleanup)
        asset_path=pathlib.Path(self.assets.name)
        shutil.copy(online.ASSETS/'default-config.json',asset_path/'default-config.json')
        (asset_path/'online-source.json').write_text(json.dumps({'repository':None,'ref':'main','path':'live/config.json'}))
        self.patch=patch.object(online,'ASSETS',asset_path);self.patch.start();self.addCleanup(self.patch.stop)
        self.config=online.validate(online.read(asset_path/'default-config.json'))
        self.source={'repository':'offline-tests/project','ref':'main','path':'live/config.json','paused':False}
        online.write(online.ROOT/'online-source.json',self.source)
        self.state={'private':'LOCAL_ONLY','items':[{'key':'existing','completed':True}]}
        (online.ROOT/'state.json').write_text(json.dumps(self.state));self.state_bytes=(online.ROOT/'state.json').read_bytes()
    def download(self,config=None):
        opener=unittest.mock.Mock()
        opener.open.side_effect=lambda request,**kwargs:Response(config or self.config,api=request.full_url.startswith('https://api.github.com/'))
        return patch.object(online.urllib.request,'build_opener',return_value=opener)
    def assert_state_untouched(self):self.assertEqual((online.ROOT/'state.json').read_bytes(),self.state_bytes)
    def test_remote_edit_changes_render_without_reinstall(self):
        with self.download():first=online.sync()
        changed=copy.deepcopy(self.config);changed['style']['header_template']='purple';changed['style']['deadline_label']='计划截止'
        changed['style']['role_colors']['由你复核']='green';changed['extraction']['guidance']=['新的提取规则，只提炼本人相关工作。']
        with self.download(changed):second=online.sync()
        self.assertTrue(first['updated']);self.assertTrue(second['updated'])
        card,mapping=render.build([{'key':'a','title':'Generic task','base_record_id':'rec_OFFLINE','base_user_role':['由你复核']}])
        self.assertEqual(card['header']['template'],'purple')
        label=card['body']['elements'][1]['elements'][0]['text']['content']
        self.assertIn("color='green'",label);self.assertIn('计划截止',label)
        self.assertIn('新的提取规则',(online.ROOT/'active-rules.md').read_text());self.assert_state_untouched()
    def test_outage_retains_last_valid_version(self):
        with self.download():online.sync()
        previous=online.read(online.ROOT/'online-cache.json')
        with patch.object(online.urllib.request,'build_opener',side_effect=online.urllib.error.URLError('offline')):
            result=online.sync()
        self.assertEqual(result['mode'],'cached_fallback');self.assertEqual(online.read(online.ROOT/'online-cache.json'),previous)
        self.assert_state_untouched()
    def test_first_outage_uses_bundled_defaults(self):
        with patch.object(online.urllib.request,'build_opener',side_effect=OSError('offline')):result=online.sync()
        self.assertEqual(result['mode'],'bundled_fallback');self.assertEqual(online.get_config(),self.config)
    def test_bad_configuration_does_not_replace_good_cache(self):
        with self.download():online.sync()
        old=(online.ROOT/'online-cache.json').read_bytes()
        bad=copy.deepcopy(self.config);bad['recipient_open_id']='INJECTED_RECIPIENT'
        with self.download(bad):result=online.sync()
        self.assertEqual(result['mode'],'cached_fallback');self.assertEqual((online.ROOT/'online-cache.json').read_bytes(),old)
        self.assert_state_untouched()
    def test_newer_client_requirement_keeps_working_config(self):
        with self.download():online.sync()
        bad=copy.deepcopy(self.config);bad['min_client']='99.0.0'
        with self.download(bad):result=online.sync()
        self.assertEqual(result['mode'],'cached_fallback');self.assertIn('newer skill',result['warning'])
    def test_conditional_get_reuses_cache(self):
        with self.download():online.sync()
        error=urllib.error.HTTPError('https://api.github.com',304,'Not Modified',{},None)
        opener=unittest.mock.Mock();opener.open.side_effect=error
        with patch.object(online.urllib.request,'build_opener',return_value=opener):result=online.sync()
        self.assertEqual(result['mode'],'online');self.assertFalse(result['updated'])
        request=opener.open.call_args.args[0];self.assertEqual(request.headers['If-none-match'],'"offline-etag"')
    def test_private_token_only_in_request_header(self):
        with patch.dict(os.environ,{'FEISHU_TODO_GITHUB_TOKEN':'LOCAL_TEST_VALUE'}),self.download() as opener:
            result=online.sync()
        request=opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(),'GET');self.assertEqual(request.headers['Authorization'],'Bearer LOCAL_TEST_VALUE')
        self.assertIsNone(request.data);self.assertTrue(request.full_url.startswith('https://api.github.com/repos/offline-tests/project/contents/live/config.json?ref=main'))
        for path in online.ROOT.rglob('*'):
            if path.is_file():self.assertNotIn('LOCAL_TEST_VALUE',path.read_text())
    def test_local_preferences_survive_remote_updates(self):
        preferences={'style':{'header_template':'orange'},'collection':{'first_scan_days':7}}
        online.write(online.ROOT/'local-preferences.json',preferences)
        with self.download():online.sync()
        self.config['style']['header_template']='green';self.config['style']['next_step_label']='我的下一步'
        with self.download():online.sync()
        self.assertEqual(online.get_config()['style']['header_template'],'orange')
        self.assertEqual(online.get_config()['style']['next_step_label'],'我的下一步')
        self.assertEqual(online.get_config()['collection']['first_scan_days'],7)
        self.assertEqual(online.read(online.ROOT/'local-preferences.json'),preferences)
    def test_rollback_pauses_subscription(self):
        with self.download():online.sync()
        self.config['style']['header_template']='orange'
        with self.download():online.sync()
        online.rollback();self.assertTrue(online.get_source()['paused'])
        self.assertEqual(online.get_config()['style']['header_template'],'blue')
        with patch.object(online,'fetch',side_effect=AssertionError('Paused must not fetch')):result=online.sync()
        self.assertEqual(result['mode'],'paused_cached')
    def test_failed_binding_preserves_previous_source(self):
        old=(online.ROOT/'online-source.json').read_bytes()
        with patch.object(online,'fetch',side_effect=RuntimeError('No access')):
            with self.assertRaises(RuntimeError):online.bind('offline-tests/another')
        self.assertEqual((online.ROOT/'online-source.json').read_bytes(),old)
    def test_invalid_paths_and_hosts_are_rejected(self):
        for repo in ['https://evil.invalid/a/b','../../etc','user/repo/extra','user/repo?token=bad']:
            with self.assertRaises(ValueError):online.repository_name(repo)
        for path in ['../state.json','/etc/config','live/../state.json','https://evil.invalid/config']:
            with self.assertRaises(ValueError):online.validate_source({**self.source,'path':path})
    def test_corrupt_cache_falls_back_without_data_loss(self):
        (online.ROOT/'online-cache.json').write_text('{broken')
        self.assertEqual(online.get_config(),self.config);self.assert_state_untouched()
    def test_unknown_style_and_template_fields_are_rejected(self):
        for key,value in [('title_template','{date.__class__}'),('show_deadline','false'),('role_colors',{'由你复核':'invalid'})]:
            bad=copy.deepcopy(self.config);bad['style'][key]=value
            with self.assertRaises(ValueError):online.validate(bad)
    def test_remote_collection_parameters_affect_actual_scan(self):
        base.rp.write_state(copy.deepcopy(base.INITIAL))
        self.config['collection']['first_scan_days']=3
        windows=[]
        def cli(args,cwd=None):
            if '+chat-list' in args:return {'meta':{'pagination':{'complete':True}},'data':{'chats':[{'chat_id':'oc_WORK','chat_mode':'group','name':'Work'}]}}
            windows.append((dt.datetime.fromisoformat(args[args.index('--start')+1]),dt.datetime.fromisoformat(args[args.index('--end')+1])))
            return {'data':{'has_more':False,'messages':[]}}
        with self.download(),patch.object(base.collect,'assert_identity'),patch.object(base.collect,'cli_json',side_effect=cli),contextlib.redirect_stdout(io.StringIO()):base.collect.main()
        self.assertEqual(windows[0][1]-windows[0][0],dt.timedelta(days=3))

if __name__=='__main__':unittest.main(verbosity=2)
