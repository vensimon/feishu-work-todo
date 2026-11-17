"""Read user checkboxes before the daily digest; never write back to the table."""
import datetime
import json
import os
import pathlib
import subprocess

from runtime_paths import ROOT, CLI_ARGS, ENV, assert_identity
from assistant_control import require_enabled,run_guarded
WORKSPACE=ROOT
STATE_FILE=ROOT/'state.json'

def main():
    generation=require_enabled()
    state = json.loads(STATE_FILE.read_text())
    assert_identity(state)
    base = state['base']
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    rows = []
    offset = 0
    while True:
        require_enabled(generation)
        relative = f'artifacts/status-sync-{offset}.ndjson'
        args = [*CLI_ARGS,'base','+record-list','--as','user','--base-token',base['base_token'],
                '--table-id',base['table_id'],'--offset',str(offset),'--format','ndjson',
                '--output',relative,'--overwrite']
        for field in ['事项','处理完毕','事项编号','跟进类型','日期说明','下一步',
                      '事项分类','来源日期','来源月份','截止日期','时间分类','通知摘要','本人职责']:
            args += ['--field-id', base['fields'][field]]
        result = subprocess.run(args,cwd=WORKSPACE,env=env,capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        manifest = json.loads(result.stdout)
        if manifest.get('ok') is False or 'records_count' not in manifest:
            raise RuntimeError('Unrecognized record response; leave prior state intact')
        page = [json.loads(line) for line in (WORKSPACE/relative).read_text().splitlines() if line.strip()]
        if len(page) != manifest['records_count']:
            raise RuntimeError('Incomplete artifact; leave prior state intact')
        rows.extend(page)
        if manifest.get('has_more') is False:
            break
        if not page:
            raise RuntimeError('Pagination did not advance')
        offset += len(page)

    by_id = {row['record_id']:row for row in rows}
    require_enabled(generation)
    by_key = {}
    for row in rows:
        key = row.get('事项编号')
        if key:
            if key in by_key:
                raise RuntimeError('Duplicate item key; do not choose a completion state arbitrarily')
            by_key[key] = row
        if type(row.get('处理完毕')) is not bool:
            raise RuntimeError('Missing/non-boolean checkbox; leave prior state intact')
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    missing=[]
    for item in state['items']:
        row = by_id.get(item.get('base_record_id'))
        if row is None:
            row = by_key.get(item['key'])
        if row is None:
            item['base_record_missing'] = True
            missing.append(item['key'])
            continue
        item['base_record_id'] = row['record_id']
        item['base_record_missing'] = False
        item['completed'] = row['处理完毕']
        item['completion_source'] = 'feishu_base_checkbox'
        item['completion_checked_at'] = now
        item['display_title'] = row.get('事项') or item['title']
        item['base_followup_type'] = row.get('跟进类型',[])
        item['base_user_role'] = row.get('本人职责',[])
        item['base_date_note'] = row.get('日期说明')
        item['base_next_step'] = row.get('下一步')
        item['base_notification_summary'] = row.get('通知摘要')
        item['base_category'] = row.get('事项分类',[])
        item['base_source_date'] = row.get('来源日期')
        item['base_source_month'] = row.get('来源月份')
        item['base_deadline_date'] = row.get('截止日期')
        item['base_time_category'] = row.get('时间分类')
    state['last_completion_sync_at'] = now
    state['completion_backend'] = 'feishu_base'
    temporary = STATE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    temporary.replace(STATE_FILE)
    work_rows=[row for row in rows if not str(row.get('事项编号','')).startswith('__')]
    print(json.dumps({'ok':True,'records':len(work_rows),'completed':sum(row['处理完毕'] for row in work_rows),
                      'pending':sum(not row['处理完毕'] for row in work_rows),'missing_keys':missing},ensure_ascii=False))

if __name__ == '__main__':
    run_guarded(main)
