"""Offline integration checks: no real Feishu calls or author account access."""
import contextlib
import copy
import importlib
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE=pathlib.Path(__file__).resolve().parents[1]/'skills/feishu-work-todo'
TEMP=tempfile.TemporaryDirectory(prefix='feishu-todo-check-')
os.environ['FEISHU_TODO_HOME']=TEMP.name
os.environ['FEISHU_TODO_PROFILE']='offline-test'
sys.path.insert(0,str(PACKAGE/'scripts'))
import runtime_paths as rp
rp.prepare_storage()
IDENTITY={'recipient_open_id':'ou_OFFLINE_PERSON','recipient_name':'Offline User','application_id':'cli_OFFLINE_APP'}
INITIAL={'version':1,**IDENTITY,'cli_profile':'offline-test','items':[],
         'base':{'base_token':'base_OFFLINE','table_id':'table_OFFLINE','url':'https://example.invalid/base/offline','fields':{}},'setup':{}}
rp.write_state(INITIAL)
import manage
import dashboard_support as ds
import render_batch_card as render
import batch_card_runtime as callbacks
import send_batch_card as sender
import collect
import verify_callback as verify
import online_config
import assistant_control
import review_audit

class FakeBase:
    def __init__(self):
        self.tables={};self.workflows=[];self.dashboards=[];self.blocks=[];self.serial=0;self.record_writes=[]
        self.add_table('待办清单',json.loads((PACKAGE/'assets/base-schema.json').read_text()),'table_OFFLINE')
    def uid(self,prefix):
        self.serial+=1;return prefix+str(self.serial)
    def add_table(self,name,fields,tid=None):
        tid=tid or self.uid('table_')
        self.tables[tid]={'id':tid,'name':name,'fields':[{**f,'id':self.uid('field_')} for f in fields],'records':[],
                          'views':[{'id':self.uid('view_'),'name':'表格'}]}
        return self.tables[tid]
    def rows(self,table,fields,stem):return copy.deepcopy(self.tables[table]['records'])
    def call(self,command,*args,table=None,body=None):
        get=lambda flag:args[args.index(flag)+1]
        if command=='+field-list':return {'fields':copy.deepcopy(self.tables[table]['fields'])}
        if command=='+field-create':
            self.tables[table]['fields'].extend({**f,'id':self.uid('field_')} for f in (body if isinstance(body,list) else [body]));return {}
        if command=='+field-get':return {'field':copy.deepcopy(next(f for f in self.tables[table]['fields'] if f['id']==get('--field-id')))}
        if command=='+field-update':
            old=next(f for f in self.tables[table]['fields'] if f['id']==get('--field-id'));old.update(body);return {}
        if command=='+table-list':return {'tables':[{'id':t['id'],'name':t['name']} for t in self.tables.values()]}
        if command=='+table-create':return self.add_table(get('--name'),json.loads(get('--fields')))
        if command=='+table-get':return self.tables[table]
        if command=='+record-batch-create':
            ids=[]
            for value in body['create_records']:
                rid=self.uid('rec_');self.tables[table]['records'].append({'record_id':rid,**value});ids.append(rid)
            return {'record_id_list':ids}
        if command=='+record-batch-update':
            self.record_writes.append(copy.deepcopy(body['update_records']))
            for rid,fields in body['update_records'].items():
                next(r for r in self.tables[table]['records'] if r['record_id']==rid).update(fields)
            return {'record_id_list':list(body['update_records'])}
        if command=='+workflow-list':return {'items':copy.deepcopy(self.workflows)}
        if command=='+workflow-create':
            item={'workflow_id':self.uid('flow_'),**body};self.workflows.append(item);return item
        if command=='+workflow-enable':return {}
        if command=='+view-list':return {'views':copy.deepcopy(self.tables[table]['views'])}
        if command=='+view-create':
            view={'id':self.uid('view_'),**body};self.tables[table]['views'].append(view);return view
        if command.startswith('+view-set-'):return {}
        if command=='+dashboard-list':return {'items':self.dashboards}
        if command=='+dashboard-create':
            item={'dashboard_id':self.uid('dash_'),'name':get('--name')};self.dashboards.append(item);return item
        if command=='+dashboard-block-list':return {'items':self.blocks,'has_more':False}
        if command=='+dashboard-block-create':
            item={'block_id':self.uid('block_'),'name':get('--name'),'type':get('--type'),'config':json.loads(get('--data-config'))};self.blocks.append(item);return item
        if command in ['+dashboard-arrange','+dashboard-get']:return {}
        raise AssertionError('Unexpected API: '+command)

class PortableTests(unittest.TestCase):
    def setUp(self):
        for path in rp.ROOT.iterdir():
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        rp.prepare_storage();rp.write_state(copy.deepcopy(INITIAL));self.base=FakeBase()
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(online_config,'get_source',return_value=None))
        self.stack.enter_context(patch.object(rp,'cli_json',return_value={'identities':{'user':{'status':'ready','available':True,'openId':IDENTITY['recipient_open_id'],'userName':'Offline User'}},'appId':IDENTITY['application_id']}))
        self.stack.enter_context(patch.object(ds,'call',side_effect=self.base.call))
        self.stack.enter_context(patch.object(ds,'rows',side_effect=self.base.rows))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.addCleanup(self.stack.close)
    def init(self):
        manage.init(True);assistant_control.set_enabled(True)
        return json.loads((rp.ROOT/'state.json').read_text())
    def proposal(self,key='a'):
        return {'key':key,'title':'Generic work','role':'由你复核','followup':'待他人反馈','category':'其他',
                'summary':'复核协作方的交付。','next_step':'等交付明确后复核。','source':{'message_id':'om_OFFLINE','chat_id':'oc_OFFLINE','time':'2026-11-17T09:00:00+08:00','url':'https://example.invalid/message'}}
    def upsert(self,plans):
        p=rp.ROOT/'proposals.json';p.write_text(json.dumps(plans))
        with patch.object(manage.subprocess,'run') as sub:
            manage.upsert(p);self.assertEqual(sub.call_count,1)
    def test_identity_mismatch_blocks_writes(self):
        with self.assertRaises(RuntimeError):rp.assert_identity({**INITIAL,'application_id':'other'})
        self.assertFalse(self.base.record_writes)
    def test_init_is_empty_and_idempotent(self):
        state=self.init();first=copy.deepcopy(state)
        self.init()
        self.assertEqual(len(self.base.tables),3);self.assertEqual(len(self.base.workflows),2)
        self.assertEqual(len(self.base.blocks),15);self.assertEqual(len(self.base.dashboards),1)
        self.assertEqual(self.base.tables['table_OFFLINE']['records'],[])
        self.assertEqual(state['items'],[]);self.assertFalse(state['setup'].get('callback_roundtrip_verified'))
        self.assertEqual(first['dashboard']['dashboard_id'],json.loads((rp.ROOT/'state.json').read_text())['dashboard']['dashboard_id'])
        workflows=self.base.workflows
        self.assertTrue(all(w['steps'][0]['data']['record_watch_info'][0]['value'][0]['value'] != w['steps'][0]['data']['field_watch_info'][0]['value'][0]['value'] for w in workflows))
    def test_upsert_preserves_manual_edits_and_completion(self):
        self.init();p=self.proposal();self.upsert([p])
        row=self.base.tables['table_OFFLINE']['records'][0]
        row['事项']='User edited';row['通知摘要']='';row['截止日期']=None
        p.update(title='AI renamed',summary='AI new summary',deadline='2026-12-01');self.upsert([p])
        self.assertEqual(row['事项'],'User edited');self.assertEqual(row['通知摘要'],'')
        # A date absent in the first extraction can be filled; an explicit user-cleared known date is retained.
        row['截止日期']=None;p['deadline']='2026-12-02';self.upsert([p]);self.assertIsNone(row['截止日期'])
        row['处理完毕']=True;p['next_step']='different';before=copy.deepcopy(row);self.upsert([p]);self.assertEqual(row,before)
    def test_deleted_and_duplicate_items_not_recreated(self):
        self.init();p=self.proposal();self.upsert([p]);self.base.tables['table_OFFLINE']['records'].clear()
        self.upsert([p]);self.assertEqual(self.base.tables['table_OFFLINE']['records'],[])
        with self.assertRaises(ValueError):self.upsert([p,p])
    def test_extractor_cannot_complete_items(self):
        self.init();p=self.proposal();p['completed']=True
        with self.assertRaises(ValueError):self.upsert([p])
        self.assertEqual(self.base.tables['table_OFFLINE']['records'],[])
    def test_option_extension_preserves_old_options(self):
        state=self.init();field=next(f for f in self.base.tables['table_OFFLINE']['fields'] if f['name']=='本人职责')
        old=copy.deepcopy(field['options']);manage.option_add('本人职责','由你协调',True)
        self.assertEqual(field['options'][:-1],old);self.assertEqual(field['options'][-1]['name'],'由你协调')
        manage.option_add('本人职责','由你协调',True);self.assertEqual(len(field['options']),len(old)+1)
    def test_card_format_and_unknown_responsibility(self):
        item={'key':'a','title':'Generic work','base_record_id':'rec_A','deadline_date':'2000-01-01','base_deadline_date':None,
              'base_notification_summary':'Review result','base_user_role':['由你评审']}
        card,mapping=render.build([item]);text=card['body']['elements'][1]['elements'][0]['text']['content']
        self.assertIn("color='purple'",text);self.assertIn('\n• 截止：未设定\n• 下一步：',text);self.assertNotIn('2000',text)
        self.assertEqual(render.responsibility({}),'职责待确认');self.assertEqual(render.role_color('新职责'),'neutral')
        self.assertEqual(len(mapping),1)
    def test_callback_only_selected_registered_owner_and_deduplicates(self):
        state=copy.deepcopy(INITIAL);state['items']=[{'key':k,'base_record_id':'rec_'+k} for k in 'abc'];rp.write_state(state)
        card,mapping=render.build([{**i,'title':i['key']} for i in state['items']])
        mid='om_OFFLINE_CARD';callbacks.save(callbacks.CARDS/(mid+'.json'),{'card':card,'mapping':mapping,'saved_keys':[]})
        event={'operator_id':state['recipient_open_id'],'message_id':mid,'action_tag':'button','action_name':'submit_done','event_id':'offline1','form_value':{'todo_001':True,'todo_002':False,'todo_003':True}}
        writes=[]
        def fake_cli(args):
            body=json.loads(args[args.index('--json')+1]);writes.append(body);return {'record_id_list':list(body['update_records'])}
        with patch.object(callbacks,'cli',side_effect=fake_cli),patch.object(callbacks,'patch',return_value={}):
            self.assertEqual(callbacks.process({**event,'operator_id':'other'})['ignored'],'different_operator')
            self.assertEqual(callbacks.process({**event,'message_id':'om_UNKNOWN'})['ignored'],'unregistered_or_preview_card')
            result=callbacks.process(event);self.assertEqual(result['selected_count'],2)
            self.assertEqual(set(writes[0]['update_records']),{'rec_a','rec_c'})
            self.assertTrue(all(v=={'处理完毕':True} for v in writes[0]['update_records'].values()))
            self.assertEqual(callbacks.process(event)['ignored'],'duplicate_event');self.assertEqual(len(writes),1)
            with self.assertRaises(ValueError):callbacks.process({**event,'event_id':'offline2','form_value':{'todo_001':'true'}})
    def test_callback_probe_can_verify_empty_installation(self):
        state=self.init();callbacks.save(rp.ROOT/'card-service-status.json',{'ready':True,'pid':os.getpid(),'consumer_pid':os.getpid()})
        with patch.object(verify,'cli',return_value={'message_id':'om_OFFLINE_PROBE'}),patch.object(sys,'argv',['verify_callback.py','send']):verify.main()
        manifest=callbacks.read(callbacks.CARDS/'om_OFFLINE_PROBE.json');self.assertEqual(manifest['mapping'],{})
        self.assertFalse(manifest['card']['body']['elements'][1]['elements'][-1]['disabled'])
        with patch.object(callbacks,'cli') as record_write,patch.object(callbacks,'patch',return_value={}):
            callbacks.process({'operator_id':state['recipient_open_id'],'message_id':'om_OFFLINE_PROBE','event_id':'probe','action_tag':'button','action_name':'submit_done','form_value':'{}'})
            record_write.assert_not_called()
        with patch.object(sys,'argv',['verify_callback.py','check']):verify.main()
        self.assertTrue(json.loads((rp.ROOT/'state.json').read_text())['setup']['callback_roundtrip_verified'])
    def test_sender_requires_probe_and_is_idempotent(self):
        state=self.init();callbacks.save(rp.ROOT/'card-service-status.json',{'ready':True,'pid':os.getpid(),'consumer_pid':os.getpid()})
        with patch.object(sys,'argv',['send_batch_card.py','--batch','offline-day']),patch.object(sender,'cli') as send:
            with self.assertRaises(RuntimeError):sender.main()
            send.assert_not_called();state['setup']['callback_roundtrip_verified']=True;rp.write_state(state)
            with self.assertRaisesRegex(RuntimeError,'review-clue audit'):sender.main()
            folder=rp.ROOT/'evidence'/'offline';folder.mkdir(parents=True)
            through='2026-01-05T10:00:00+08:00'
            (folder/'messages.json').write_text('[]')
            (folder/'manifest.json').write_text(json.dumps({'complete':True,'through':through,'messages':0}))
            ledger=folder/'ledger.json';ledger.write_text('[]')
            review_audit.finish(folder,ledger,through,state)
            state['last_successful_scan_at']=through;rp.write_state(state)
            send.return_value={'message_id':'om_OFFLINE_SENT'};sender.main();sender.main();self.assertEqual(send.call_count,1)
    def test_collect_excludes_topics_before_reading(self):
        chats=[{'chat_id':'oc_TOPIC','chat_mode':'topic','name':'Work topic'},
               {'chat_id':'oc_UNKNOWN','name':'Unknown'},
               {'chat_id':'oc_BOT','chat_mode':'p2p','p2p_target_type':'bot'},
               {'chat_id':'oc_SOCIAL','chat_mode':'group','name':'表情包'},
               {'chat_id':'oc_WORK','chat_mode':'group','name':'Work'},
               {'chat_id':'oc_PERSON','chat_mode':'p2p','p2p_target_type':'user'}]
        def fake(args,cwd=None):
            if '+chat-list' in args:return {'meta':{'pagination':{'complete':True}},'data':{'chats':chats}}
            ids=args[args.index('--chat-id')+1].split(',');self.assertEqual(set(ids),{'oc_WORK','oc_PERSON'})
            return {'data':{'has_more':False,'messages':[{'chat_id':'oc_WORK','message_id':'om_OFFLINE'}]}}
        with patch.object(collect,'cli_json',side_effect=fake):collect.main()
        manifest=json.loads(next((rp.ROOT/'evidence').glob('*/manifest.json')).read_text())
        self.assertEqual(manifest['eligible_chats'],2);self.assertEqual(manifest['messages'],1)
        self.assertNotIn('last_successful_scan_at',json.loads((rp.ROOT/'state.json').read_text()))
    def test_no_personal_data_or_runtime_in_package(self):
        forbidden=[r'(?:ou_|oc_|om_|cli_)[0-9a-f]{20,}','/'+'Users/[^/\\s]+/']
        for file in PACKAGE.rglob('*'):
            if not file.is_file() or '__pycache__' in file.parts:continue
            content=file.read_text()
            for pattern in forbidden:self.assertIsNone(re.search(pattern,content),str(file))
            self.assertNotIn(file.name,['state.json','card-submissions.json','credentials.json'])

if __name__=='__main__':unittest.main(verbosity=2)
