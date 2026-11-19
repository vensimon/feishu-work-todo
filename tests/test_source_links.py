"""Message origins stay separate from completion controls and survive card updates."""
import copy
import unittest

import test_portable as base
import render_batch_card as render
import batch_card_runtime as callbacks
from checklist_selection import elements

SOURCE='https://applink.feishu.cn/client/chat/open?openChatId=oc_TEST_CHAT&position=42'

class SourceLinkTests(unittest.TestCase):
    def setUp(self):
        self.config=copy.deepcopy(base.online_config.read(base.PACKAGE/'assets/default-config.json'))
        self.items=[{'key':'a','title':'Review draft','base_record_id':'rec_TEST_A',
                     'message_app_link':SOURCE,'base_user_role':['由你复核']}]

    def build(self):return render.build(self.items,config=self.config)

    def test_each_task_has_a_precise_link_outside_the_completion_control(self):
        card,mapping=self.build()
        checker,source,submit=elements(card)
        self.assertEqual(source['content'],'[查看原消息 ↗]('+SOURCE+')')
        self.assertEqual(source['text_size'],'notation')
        self.assertNotIn('behaviors',source);self.assertNotIn('name',source)
        self.assertEqual(submit['form_action_type'],'submit')
        self.assertEqual(mapping,{'todo_001':{'key':'a','record_id':'rec_TEST_A'}})
        self.assertEqual(checker['name'],'todo_001')

    def test_completion_keeps_source_link_clickable_and_only_changes_the_checker(self):
        card,mapping=self.build()
        manifest={'card':card,'mapping':mapping,'saved_keys':[]}
        source=copy.deepcopy(elements(card)[1])
        updated=callbacks.refresh_card(manifest,{'a'},1)
        checker,link,submit=elements(updated)
        self.assertTrue(checker['checked']);self.assertTrue(checker['disabled'])
        self.assertEqual(link,source);self.assertNotIn('disabled',link)
        self.assertTrue(submit['disabled'])

    def test_existing_card_amendment_is_idempotent_and_preserves_every_control(self):
        card,mapping=self.build();controls_list=elements(card)
        controls_list[:]=[e for e in controls_list if e['tag']!='markdown']
        controls_list[0].update(checked=True,disabled=True)
        controls=copy.deepcopy(controls_list);original_mapping=copy.deepcopy(mapping)
        render.add_source_links(card,mapping,self.items)
        once=copy.deepcopy(card);render.add_source_links(card,mapping,self.items)
        self.assertEqual(card,once);self.assertEqual(mapping,original_mapping)
        self.assertEqual([e for e in elements(card) if e['tag']!='markdown'],controls)

    def test_multiple_tasks_keep_their_own_sources(self):
        self.items.append({'key':'b','title':'Confirm plan','base_record_id':'rec_TEST_B',
                           'message_app_link':SOURCE.replace('position=42','position=99')})
        card,mapping=self.build();controls=elements(card)
        by_key={i['key']:i for i in self.items}
        for n,element in enumerate(controls):
            if element['tag']=='checker':
                self.assertIn(by_key[mapping[element['name']]['key']]['message_app_link'],controls[n+1]['content'])

    def test_unknown_source_is_explicit_and_never_replaced_with_a_chat_home(self):
        self.items[0].pop('message_app_link')
        card,_=self.build();link=elements(card)[1]
        self.assertIn('原消息链接待补充',link['content']);self.assertNotIn('](',link['content'])
        self.assertNotIn('openChatId',link['content'])

    def test_table_origin_precedes_collected_origin_and_latest_evidence_is_only_a_fallback(self):
        override=SOURCE.replace('position=42','position=12')
        item={**self.items[0],'base_message_app_link':override,'latest_evidence':{'url':SOURCE+'0'}}
        self.assertEqual(render.source_message_url(item),override)
        item.pop('base_message_app_link');self.assertEqual(render.source_message_url(item),SOURCE)
        item.pop('message_app_link');self.assertEqual(render.source_message_url(item),SOURCE+'0')

    def test_unsafe_and_malformed_urls_do_not_create_links(self):
        for url in ['javascript:alert(1)','file:///tmp/message','https://example.invalid/x\nInjected',
                    'https://name:secret@example.invalid/message','https://[broken',
                    'https://example.invalid/x\\bad','https://example.invalid/<tag>']:
            with self.subTest(url=url):
                self.assertIsNone(render.source_message_url({'message_app_link':url}))

    def test_deleted_completed_and_internal_tasks_are_still_excluded(self):
        self.items.extend([{**self.items[0],'key':'done','completed':True},
                           {**self.items[0],'key':'gone','base_record_missing':True},
                           {**self.items[0],'key':'__probe'}])
        card,mapping=self.build()
        self.assertEqual(len(mapping),1)
        self.assertEqual(sum(e['tag']=='markdown' for e in elements(card)),1)

    def test_amending_a_different_record_is_rejected(self):
        card,mapping=self.build();mapping['todo_001']['record_id']='rec_STALE'
        with self.assertRaisesRegex(ValueError,'mapping mismatch'):
            render.add_source_links(card,mapping,self.items)

if __name__=='__main__':unittest.main(verbosity=2)
