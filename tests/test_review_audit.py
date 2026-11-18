"""Review-round regression cases use fictional messages and no connected account."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'skills/feishu-work-todo/scripts'))
import review_audit as audit

OWNER = 'ou_TEST_REVIEWER'

def message(mid, text, minute, owner=False, kind='text'):
    return {'message_id': mid, 'chat_id': 'oc_TEST_CHAT', 'content': text,
            'create_time': f'2026-01-05 15:{minute:02d}', 'msg_type': kind,
            'sender': {'id': OWNER if owner else 'ou_TEST_DESIGNER'}}

class ReviewAuditTests(unittest.TestCase):
    def setUp(self):
        self.messages = [message('om_FIRST', '方案甲', 1),
                         message('om_REVIEWED', '我看完了，你再看看问题', 2, True),
                         message('om_REVISION', '设计稿更新咯', 3),
                         message('om_CHANGE', '需求有些变更，请把设计稿更新一下，列表和弹窗字段调整。', 4, kind='merge_forward')]
        self.state = {'recipient_open_id': OWNER, 'items': [
            {'key': 'review-a', 'base_record_id': 'rec_TEST_A', 'completed': False},
            {'key': 'review-b', 'base_record_id': 'rec_TEST_B', 'completed': False}]}
        self.ledger = [dict(candidate_id=mid, decision='task', item_key=key,
                            reason='本人需复核，协作方负责设计修改。', evidence_ids=[mid])
                       for mid, key in [('om_REVISION', 'review-a'), ('om_CHANGE', 'review-b')]]
    def test_both_revision_and_forwarded_changes_are_nominated(self):
        candidates = audit.nominate(self.messages, OWNER)
        self.assertEqual({c['candidate_id'] for c in candidates}, {'om_REVISION', 'om_CHANGE'})
        self.assertEqual(audit.validate(self.messages, OWNER, self.ledger, self.state)['counts']['task'], 2)
    def test_silent_omission_blocks_scan(self):
        with self.assertRaisesRegex(ValueError, 'Every nominated'):
            audit.validate(self.messages, OWNER, self.ledger[:1], self.state)
    def test_old_review_cannot_close_new_revision(self):
        self.ledger[0].update(decision='exclude', reason_code='user_completed_after',
                              evidence_ids=['om_REVIEWED'], completion_quote='我看完了')
        with self.assertRaisesRegex(ValueError, 'later explicit'):
            audit.validate(self.messages, OWNER, self.ledger, self.state)
    def test_another_executor_is_not_a_valid_exclusion(self):
        self.ledger[1].update(decision='exclude', reason_code='other_person_executes')
        with self.assertRaisesRegex(ValueError, 'another executor'):
            audit.validate(self.messages, OWNER, self.ledger, self.state)
    def test_ambiguous_project_is_retained_and_carried_beyond_window(self):
        self.ledger[1].update(decision='needs_confirmation', label='确认方案乙的本人审核范围')
        report = audit.validate(self.messages, OWNER, self.ledger, self.state)
        self.assertEqual(len(report['pending_candidates']), 1)
        self.state['review_candidates'] = report['pending_candidates']
        carried = audit.nominate([], OWNER, audit.pending_items(self.state))
        self.assertEqual(carried[0]['candidate_id'], 'om_CHANGE')
        with self.assertRaises(ValueError): audit.validate([], OWNER, [], self.state)
    def test_later_owner_completion_can_close_this_round(self):
        self.messages.append(message('om_DONE', '更新稿我复核完成了', 6, True))
        self.ledger[0].update(decision='exclude', reason_code='user_completed_after',
                              evidence_ids=['om_DONE'], completion_quote='复核完成')
        report = audit.validate(self.messages, OWNER, self.ledger, self.state)
        self.assertEqual(report['counts']['exclude'], 1)
    def test_negative_or_third_party_completion_cannot_close_owner_review(self):
        for text, owner in [('我还没看完', True), ('我看完了', False)]:
            with self.subTest(text=text, owner=owner):
                messages = self.messages + [message('om_NOT_OWNER_CLOSURE', text, 6, owner)]
                ledger = copy.deepcopy(self.ledger)
                ledger[0].update(decision='exclude', reason_code='user_completed_after',
                                 evidence_ids=['om_NOT_OWNER_CLOSURE'], completion_quote='看完')
                with self.assertRaisesRegex(ValueError, 'later explicit'):
                    audit.validate(messages, OWNER, ledger, self.state)
    def test_old_completed_task_cannot_absorb_new_review_round(self):
        self.state['items'][0]['completed'] = True
        with self.assertRaisesRegex(ValueError, 'completed prior round'):
            audit.validate(self.messages, OWNER, self.ledger, self.state)
    def test_actual_checkbox_confirmation_after_clue_closes_it(self):
        self.state['items'][0].update(completed=True, base_completed_at='2026-01-05T15:05:00+08:00')
        self.ledger[0].update(decision='exclude', reason_code='recorded_completion', item_key='review-a',
                              reason='本人已在回稿后勾选完成，有实际确认时间。')
        self.assertEqual(audit.validate(self.messages, OWNER, self.ledger, self.state)['counts']['exclude'], 1)
    def test_old_checkbox_or_recent_sync_cannot_close_new_revision(self):
        for closed in ['2026-01-05T15:01:00+08:00', None]:
            with self.subTest(closed=closed):
                self.state['items'][0].update(completed=True, base_completed_at=closed,
                                              completion_checked_at='2026-01-06T12:00:00+08:00')
                self.ledger[0].update(decision='exclude', reason_code='recorded_completion', item_key='review-a')
                with self.assertRaisesRegex(ValueError, 'actual confirmation time'):
                    audit.validate(self.messages, OWNER, self.ledger, self.state)
    def test_prior_review_survives_intervening_messages(self):
        gap = [message(f'om_CHAT_{i}', '讨论节点进度', i+3, i % 2 == 0) for i in range(7)]
        messages = self.messages[:2] + gap + [message('om_REVISION', '设计稿更新咯', 15)]
        candidate = audit.nominate(messages, OWNER)[0]
        self.assertIn('om_REVIEWED', candidate['prior_review_ids'])
        ledger = [dict(candidate_id='om_REVISION', decision='exclude', reason='只是更新',
                       reason_code='informational_only', evidence_ids=['om_REVISION'])]
        with self.assertRaisesRegex(ValueError, 'later owner closure'):
            audit.validate(messages, OWNER, ledger, self.state)
    def test_unrelated_information_can_be_excluded_with_recorded_evidence(self):
        self.ledger[1].update(decision='exclude', reason_code='unrelated_to_user',
                              reason='转发内容明确指定其他审核人，与本人无关。')
        self.assertEqual(audit.validate(self.messages, OWNER, self.ledger, self.state)['counts']['exclude'], 1)
    def test_update_request_is_not_final_delivery(self):
        candidates = audit.nominate(self.messages, OWNER)
        change = next(c for c in candidates if c['candidate_id'] == 'om_CHANGE')
        self.assertIn('revision_progress', change['kinds'])
        self.assertNotIn('revision', change['kinds'])
    def test_owner_can_explicitly_delegate_review_but_designer_cannot(self):
        for owner in [True, False]:
            with self.subTest(owner=owner):
                messages = self.messages + [message('om_DELEGATE', '我和同事说下，让她审核吧。', 6, owner)]
                ledger = copy.deepcopy(self.ledger)
                if not owner:
                    ledger.append(dict(candidate_id='om_DELEGATE', decision='needs_confirmation',
                                       label='核对审核转交人', reason='对方不能替本人确认转交。', evidence_ids=['om_DELEGATE']))
                ledger[0].update(decision='exclude', reason_code='delegated_by_user',
                                 evidence_ids=['om_DELEGATE'], delegation_quote='让她审核')
                if owner:
                    self.assertEqual(audit.validate(messages, OWNER, ledger, self.state)['counts']['exclude'], 1)
                else:
                    with self.assertRaisesRegex(ValueError, 'owner later explicitly'):
                        audit.validate(messages, OWNER, ledger, self.state)
    def test_unknown_evidence_and_duplicate_dispositions_fail(self):
        ledger = copy.deepcopy(self.ledger); ledger[0]['evidence_ids'] = ['om_INVENTED']
        with self.assertRaises(ValueError): audit.validate(self.messages, OWNER, ledger, self.state)
        with self.assertRaises(ValueError): audit.validate(self.messages, OWNER, self.ledger + self.ledger[:1], self.state)
    def test_send_requires_matching_unchanged_audit_but_allows_user_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp); through = '2026-01-05T16:00:00+08:00'
            (folder/'messages.json').write_text(json.dumps(self.messages))
            (folder/'manifest.json').write_text(json.dumps({'complete': True, 'through': through, 'messages': len(self.messages)}))
            ledger = folder/'ledger.json'; ledger.write_text(json.dumps(self.ledger))
            with self.assertRaises(RuntimeError): audit.require_current_audit(self.state)
            audit.finish(folder, ledger, through, self.state)
            self.state['last_successful_scan_at'] = through
            self.state['items'][0]['completed'] = True
            audit.require_current_audit(self.state)
            ledger.write_text('[]')
            with self.assertRaisesRegex(RuntimeError, 'changed'): audit.require_current_audit(self.state)
    def test_empty_scan_still_has_explicit_audit(self):
        self.assertEqual(audit.validate([], OWNER, [], self.state)['counts'],
                         {'task': 0, 'needs_confirmation': 0, 'exclude': 0})

if __name__ == '__main__': unittest.main()
