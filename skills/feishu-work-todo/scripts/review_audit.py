"""Nominate review clues and validate explicit dispositions, without deciding duties."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re

REVIEW = re.compile(r'审核|复核|评审|验收|审下|请.{0,8}看|帮.{0,8}看|再看|看看|看下|看一下|过一下')
REVISION = re.compile(r'回稿|改好了|改好啦|已修改|修改完|设计稿.{0,10}(更新|调整)|更新.{0,10}(设计稿|稿件)|方案.{0,8}更新')
REVISION_IN_PROGRESS = re.compile(r'(请|麻烦|需要|准备|正在|还在|待).{0,16}(更新|调整|修改)|正在|还在')
CHANGE = re.compile(r'变更|需求.{0,8}(调整|修改)|字段.{0,8}更新')
REVIEWED = re.compile(r'看完|审完|已审|评审完成|复核完成|审核通过|验收通过')
COMPLETE = re.compile(r'看完|审完|已审|评审完成|复核完成|审核通过|验收通过|没(?:有)?问题|无异议|不用.{0,8}(审核|复核)|无需.{0,8}(审核|复核)')
NOT_COMPLETE = re.compile(r'(没|未|尚未|还没|待).{0,4}(看完|审完|已审|评审完成|复核完成|审核通过|验收通过)')
DELEGATED = re.compile(r'让.{0,8}(审核|复核|评审)|交给|负责人.{0,8}改|由.{0,8}(审核|复核|评审)')

def sender_id(message):
    sender = message.get('sender') or {}
    return sender.get('id') or sender.get('open_id')

def timestamp(message):
    value = message.get('create_time') or message.get('source_time')
    if not isinstance(value, str):
        raise ValueError('Review evidence needs an explicit timestamp')
    value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return value

def fingerprint(messages):
    raw = json.dumps(sorted(messages, key=lambda m: m['message_id']), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def pending_items(state):
    value = state.get('review_candidates', [])
    return value if isinstance(value, list) else []

def nominate(messages, owner, pending=()):
    """High-recall clues only; regexes never create, complete, or assign a task."""
    by_chat = {}
    for message in messages:
        by_chat.setdefault(message['chat_id'], []).append(message)
    result = {p['candidate_id']: p for p in pending}
    for chat_messages in by_chat.values():
        chat_messages.sort(key=lambda m: (m.get('create_time', ''), m['message_id']))
        for index, message in enumerate(chat_messages):
            if sender_id(message) == owner:
                continue
            text = message.get('content') or ''
            kinds = []
            if REVIEW.search(text): kinds.append('review_request')
            if REVISION.search(text):
                kinds.append('revision_progress' if REVISION_IN_PROGRESS.search(text) else 'revision')
            if message.get('msg_type') == 'merge_forward' and CHANGE.search(text):
                kinds.append('forwarded_change')
            if not kinds:
                continue
            earlier_reviews = [m for m in chat_messages[:index]
                               if sender_id(m) == owner and REVIEWED.search(m.get('content') or '')][-2:]
            context = list({m['message_id']: m for m in
                            earlier_reviews + chat_messages[max(0, index-5):index+6]}.values())
            prior = [m['message_id'] for m in earlier_reviews]
            result[message['message_id']] = {
                'candidate_id': message['message_id'], 'chat_id': message['chat_id'],
                'kinds': kinds, 'prior_review_ids': prior, 'context': context}
            old = next((p for p in pending if p['candidate_id'] == message['message_id']), None)
            if old:
                current = result[message['message_id']]
                current['context'] = list({m['message_id']: m for m in old['context'] + context}.values())
                current['prior_review_ids'] = sorted(set(old['prior_review_ids'] + prior))
    return list(result.values())

def validate(messages, owner, ledger, state):
    candidates = nominate(messages, owner, pending_items(state))
    expected = {c['candidate_id']: c for c in candidates}
    if not isinstance(ledger, list):
        raise ValueError('Review ledger must be an array')
    by_id = {}
    for row in ledger:
        cid = row['candidate_id']
        if cid in by_id:
            raise ValueError('Duplicate review disposition: ' + cid)
        by_id[cid] = row
    if set(by_id) != set(expected):
        raise ValueError('Every nominated review clue needs one disposition; missing=' +
                         str(sorted(set(expected)-set(by_id))) + '; unknown=' + str(sorted(set(by_id)-set(expected))))
    tasks = {i['key']: i for i in state['items']}
    unresolved = []
    counts = {'task': 0, 'needs_confirmation': 0, 'exclude': 0}
    for cid, candidate in expected.items():
        row = by_id[cid]
        decision = row.get('decision')
        if decision not in counts or not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError('Each clue needs a decision and a concrete reason: ' + cid)
        context = {m['message_id']: m for m in candidate['context']}
        evidence = row.get('evidence_ids')
        if not isinstance(evidence, list) or not evidence or any(e not in context for e in evidence):
            raise ValueError('Disposition needs real evidence from the clue context: ' + cid)
        if decision == 'task':
            item = tasks.get(row.get('item_key'))
            if not item or not item.get('base_record_id') or item.get('completed') or item.get('base_record_missing'):
                raise ValueError('Review clue must map to a live pending task, not a completed prior round: ' + cid)
        elif decision == 'needs_confirmation':
            label = row.get('label')
            if not isinstance(label, str) or not label.strip() or len(label) > 60:
                raise ValueError('Uncertain clue needs a short label for the user: ' + cid)
            unresolved.append({**candidate, 'label': label, 'reason': row['reason']})
        else:
            code = row.get('reason_code')
            if code not in {'informational_only', 'unrelated_to_user', 'not_actionable', 'user_completed_after', 'delegated_by_user', 'recorded_completion'}:
                raise ValueError('Ambiguity, another executor, or an earlier review cannot exclude a clue: ' + cid)
            if candidate['prior_review_ids'] and 'revision' in candidate['kinds'] and code not in {'user_completed_after','delegated_by_user','recorded_completion'}:
                raise ValueError('A revision after the owner review needs a task, confirmation, or later owner closure: ' + cid)
            if code == 'user_completed_after':
                origin = context[cid]
                later = [context[e] for e in evidence if sender_id(context[e]) == owner and
                         timestamp(context[e]) > timestamp(origin) and
                         COMPLETE.search(context[e].get('content') or '') and
                         not NOT_COMPLETE.search(context[e].get('content') or '')]
                quote = row.get('completion_quote', '')
                if not quote or not any(quote in m.get('content', '') and COMPLETE.search(quote) for m in later):
                    raise ValueError('Closing this round requires a later explicit owner completion quote: ' + cid)
            if code == 'delegated_by_user':
                later = [context[e] for e in evidence if sender_id(context[e]) == owner and
                         timestamp(context[e]) > timestamp(context[cid])]
                quote = row.get('delegation_quote', '')
                if not quote or not DELEGATED.search(quote) or not any(quote in m.get('content', '') for m in later):
                    raise ValueError('Delegation requires the owner later explicitly transferring review duty: ' + cid)
            if code == 'recorded_completion':
                item = tasks.get(row.get('item_key'), {})
                closed = item.get('base_completed_at')
                if (not item.get('completed') or not item.get('base_record_id') or not closed or
                        timestamp({'source_time': closed}) <= timestamp(context[cid])):
                    raise ValueError('Checkbox closure needs its actual confirmation time after this clue, not the last sync time: ' + cid)
        counts[decision] += 1
    return {'status': 'validated', 'evidence_digest': fingerprint(messages),
            'owner_id': owner, 'counts': counts, 'pending_candidates': unresolved}

def finish(evidence_dir, ledger_file, through, state, source_ledger=None):
    folder = pathlib.Path(evidence_dir)
    manifest = json.loads((folder/'manifest.json').read_text())
    if manifest.get('complete') is not True or manifest.get('through') != through:
        raise ValueError('Review audit must match a complete collection and exact scan watermark')
    messages = json.loads((folder/'messages.json').read_text())
    if len(messages) != manifest.get('messages'):
        raise ValueError('Evidence count differs from collection manifest')
    ledger_bytes = pathlib.Path(ledger_file).read_bytes()
    report = validate(messages, state['recipient_open_id'], json.loads(ledger_bytes), state)
    if (folder/'source-evidence.json').exists():
        if not source_ledger:raise ValueError('Review all meeting and notification sources with --source-ledger')
        from work_sources import validate_ledger
        validate_ledger(folder,source_ledger,state)
    report.update(through=through, evidence_directory=str(folder.resolve()), ledger_file=str(pathlib.Path(ledger_file).resolve()))
    report['ledger_digest'] = hashlib.sha256(ledger_bytes).hexdigest()
    state['review_audit'] = report
    state['review_candidates'] = report['pending_candidates']
    return report

def require_current_audit(state):
    audit = state.get('review_audit', {})
    if (not state.get('last_successful_scan_at') or audit.get('status') != 'validated' or
            audit.get('through') != state['last_successful_scan_at'] or
            audit.get('owner_id') != state.get('recipient_open_id')):
        raise RuntimeError('Complete the review-clue audit for this scan before sending a work checklist')
    # Completion may change after preparation; verify artifacts without re-opening work.
    folder = pathlib.Path(audit['evidence_directory'])
    from work_sources import require_audit
    require_audit(folder,state)
    manifest = json.loads((folder/'manifest.json').read_text())
    messages = json.loads((folder/'messages.json').read_text())
    if (manifest.get('complete') is not True or manifest.get('through') != audit['through'] or
            manifest.get('messages') != len(messages) or
            fingerprint(messages) != audit.get('evidence_digest') or
            hashlib.sha256(pathlib.Path(audit['ledger_file']).read_bytes()).hexdigest() != audit.get('ledger_digest')):
        raise RuntimeError('Evidence or decisions changed after review audit')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--messages', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--ledger')
    parser.add_argument('--evidence-dir')
    parser.add_argument('--through')
    parser.add_argument('--source-ledger')
    parser.add_argument('--record', action='store_true', help='Persist a validated report and pending clues in this state')
    args = parser.parse_args()
    messages = json.loads(pathlib.Path(args.messages).read_text())
    state = json.loads(pathlib.Path(args.state).read_text())
    if args.ledger:
        if not args.evidence_dir or not args.through:
            parser.error('Validation requires --evidence-dir and --through')
        report = finish(args.evidence_dir, args.ledger, args.through, state,args.source_ledger)
        pathlib.Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        if args.record:
            path = pathlib.Path(args.state)
            temp = path.with_name(path.name + '.audit.tmp')
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            temp.replace(path)
        print(json.dumps({'status': report['status'], 'counts': report['counts']}))
        return
    if args.record:
        parser.error('--record requires a validated ledger')
    candidates = nominate(messages, state['recipient_open_id'], pending_items(state))
    output = {'candidates': candidates, 'ledger_template': [
        {'candidate_id': c['candidate_id'], 'decision': None, 'reason': '',
         'evidence_ids': [c['candidate_id']]} for c in candidates]}
    pathlib.Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({'candidates': len(candidates), 'output': args.output}))

if __name__ == '__main__': main()
