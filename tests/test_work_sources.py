"""Authorized source reading and explicit filtering, without network or real accounts."""
import copy
import datetime as dt
import json
import pathlib
import tempfile
import unittest

import test_portable as base
import work_sources as sources

class WorkSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name);self.folder=self.root/'scan';self.folder.mkdir()
        self.state={**copy.deepcopy(base.INITIAL),'source_settings':{'minutes_enabled':False,'meeting_search_enabled':False}}
        self.now=dt.datetime(2026,1,5,10,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        self.calls=[]
    def notification(self,text='有人在文档中提及你 https://example.feishu.cn/docx/DOC_TEST'):
        return {'message_id':'om_SOURCE_TEST','chat_id':'oc_SOURCE_TEST','content':text,'create_time':'2026-01-05 09:00',
                'notification_source':'云文档助手','message_app_link':'https://applink.feishu.cn/client/chat/open?openChatId=oc_SOURCE_TEST&position=1'}
    def call(self,args,cwd=None):
        self.calls.append(args)
        if args[:2]==['docs','+fetch']:
            return {'ok':True,'data':{'document':{'document_id':'DOC_TEST','content':'请负责人核对方案。',
                     'reference_map':{'comments':{'c1':{'data':'<comment><quote>方案</quote><msg>请复核</msg></comment>'}}}}}}
        if args[:2]==['minutes','+search']:
            return {'ok':True,'data':{'items':[{'token':'MINUTE_TEST','meta_data':{'app_link':'https://example.feishu.cn/minutes/MINUTE_TEST'}}],'has_more':False}}
        if args[:2]==['minutes','+detail']:
            path=self.root/args[args.index('--output-dir')+1]/'original.txt';path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('2026-01-05 09:00:00 CST\n甲：请本人核对，其他同事负责制作。')
            return {'ok':True,'data':{'minutes':[{'minute_token':'MINUTE_TEST','title':'方案会议',
                    'artifacts':{'todos':[],'transcript_file':str(path.relative_to(self.root))}}]}}
        if args[:2]==['base','+record-get']:return {'ok':True,'data':{'records':[{'record_id':'rec_TEST','fields':{'任务':'核对方案'}}]}}
        raise RuntimeError('Missing required scope: vc:meeting.search:read')
    def collect(self,messages):
        return sources.collect(self.folder,self.root,messages,self.state,self.now-dt.timedelta(days=15),self.now,self.call)
    def evidence(self):return json.loads((self.folder/'source-evidence.json').read_text())
    def ledger(self):
        rows=[{'source_id':r['source_id'],'decision':'exclude','reason_code':'informational_only','reason':'仅通知，没有本人行动'} for r in self.evidence()['sources']]
        p=self.folder/'ledger.json';p.write_text(json.dumps(rows));return p,rows
    def test_only_selected_work_bots_are_added_and_topics_stay_excluded(self):
        chat={'chat_id':'oc_NOTIFY','chat_mode':'p2p','p2p_target_type':'bot','name':'云文档助手'}
        self.assertTrue(sources.notification_chat(chat,self.state))
        self.assertFalse(sources.notification_chat({**chat,'chat_mode':'topic'},self.state))
        self.assertFalse(sources.notification_chat({**chat,'name':'其他机器人'},self.state))
    def test_notification_actor_mention_does_not_mean_the_owner_was_mentioned(self):
        message=self.notification('甲与你分享了文件 https://example.feishu.cn/docx/DOC_TEST')
        message['mentions']=[{'id':'ou_OTHER_ACTOR'}]
        self.assertFalse(sources.mentioned(message,self.state['recipient_open_id']))
        self.collect([message]);self.assertEqual(self.calls,[])
        self.assertEqual(len(self.evidence()['sources']),1)
    def test_document_mention_fetches_body_and_comment_context_without_writing(self):
        self.collect([self.notification()])
        read=self.evidence()['sources'];self.assertEqual(len(read),2)
        doc=next(r for r in read if r['kind']=='docx')
        raw=json.loads((self.folder/doc['evidence_file']).read_text())
        self.assertIn('comments',raw['document']['reference_map'])
        self.assertEqual(self.calls[0][:2],['docs','+fetch'])
    def test_base_mention_reads_only_the_named_record(self):
        self.collect([self.notification('有人在多维表格中提及你 https://example.feishu.cn/base/BASE_TEST?table=tblTEST&record=rec_TEST')])
        self.assertEqual(self.calls[0][:2],['base','+record-get'])
        self.assertEqual(self.calls[0][self.calls[0].index('--record-id')+1],'rec_TEST')
    def test_table_only_mention_remains_pending_instead_of_inventing_a_row(self):
        self.collect([self.notification('有人在多维表格中提及你 https://example.feishu.cn/base/BASE_TEST?table=tblTEST')])
        record=next(r for r in self.evidence()['sources'] if r['kind']=='base_record')
        self.assertEqual(record['status'],'context_missing');self.assertEqual(self.calls,[])
        p,rows=self.ledger()
        with self.assertRaisesRegex(ValueError,'Unread source'):sources.validate_ledger(self.folder,p,self.state)
    def test_meeting_transcript_is_read_once_for_owned_and_participated_results(self):
        self.state['source_settings']['minutes_enabled']=True
        self.collect([])
        rows=self.evidence()['sources'];self.assertEqual(len(rows),1)
        self.assertTrue((self.folder/rows[0]['transcript_file']).is_file())
        self.assertEqual(sum(c[:2]==['minutes','+detail'] for c in self.calls),1)
        self.assertEqual(rows[0]['time'],'2026-01-05T09:00:00+08:00')
    def test_missing_permission_is_explicit_and_cannot_be_silently_excluded(self):
        self.state['source_settings']['meeting_search_enabled']=True
        self.collect([]);self.assertFalse(self.evidence()['coverage']['meetings']['complete'])
        p,rows=self.ledger()
        with self.assertRaisesRegex(ValueError,'Unread source'):sources.validate_ledger(self.folder,p,self.state)
        rows[0].update(decision='needs_confirmation',label='会议检索权限待开通');p.write_text(json.dumps(rows))
        sources.validate_ledger(self.folder,p,self.state)
        self.assertNotIn('meetings',self.state['source_watermarks'])
        self.assertEqual(len(self.state['source_candidates']),1)
    def test_all_source_dispositions_are_required_and_receipt_changes_are_detected(self):
        self.collect([self.notification()]);p,rows=self.ledger();p.write_text('[]')
        with self.assertRaisesRegex(ValueError,'Every meeting'):sources.validate_ledger(self.folder,p,self.state)
        p.write_text(json.dumps(rows));sources.validate_ledger(self.folder,p,self.state)
        sources.require_audit(self.folder,self.state)
        p.write_text('[]')
        with self.assertRaisesRegex(RuntimeError,'decisions changed'):sources.require_audit(self.folder,self.state)
    def test_native_minutes_can_create_a_task_without_fake_message_or_chat_ids(self):
        probe=base.PortableTests('test_init_is_empty_and_idempotent');probe.setUp()
        try:
            probe.init();p=probe.proposal();p['source']={'kind':'minutes','id':'MINUTE_TEST','url':'https://example.feishu.cn/minutes/MINUTE_TEST','time':'2026-01-05T09:00:00+08:00'}
            probe.upsert([p]);item=json.loads((base.rp.ROOT/'state.json').read_text())['items'][0]
            self.assertIsNone(item['message_id']);self.assertEqual(item['origin_kind'],'minutes')
            self.assertIn('查看纪要',base.render.source_link_element(item,'todo_001')['content'])
        finally:probe.doCleanups()
    def test_new_meeting_round_cannot_be_closed_by_an_older_checkbox(self):
        self.state['source_settings']['minutes_enabled']=True;self.collect([])
        self.state['items']=[{'key':'old','base_record_id':'rec_OLD','completed':True,'base_completed_at':'2026-01-04T12:00:00+08:00'}]
        p,rows=self.ledger();rows[0].update(reason_code='recorded_completion',item_key='old');p.write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError,'older completion'):sources.validate_ledger(self.folder,p,self.state)
    def test_external_and_injected_links_are_not_followed(self):
        self.collect([self.notification('在文档中提及你 https://evil.invalid/docx/DOC https://evil.invalid@x.feishu.cn/docx/DOC')])
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
