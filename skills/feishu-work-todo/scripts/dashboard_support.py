"""Small CLI adapter and calendar rows for the live native Feishu dashboard."""
import datetime as dt
import json
import os
import pathlib
import subprocess

from runtime_paths import ROOT, CLI_ARGS, ENV
WORKSPACE=ROOT
CONFIG=json.loads((ROOT/'state.json').read_text())
BASE=CONFIG['base']['base_token']
TABLE=CONFIG['base']['table_id']
TZ=dt.timezone(dt.timedelta(hours=8))

def save(name,data):
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2))

def call(command,*args,table=None,body=None):
    argv=[*CLI_ARGS,'base',command,'--base-token',BASE,'--as','user',*args]
    if table:argv+=['--table-id',table]
    if body is not None:argv+=['--json',json.dumps(body,ensure_ascii=False)]
    p=subprocess.run(argv,cwd=WORKSPACE,env=ENV,capture_output=True,text=True,timeout=120)
    data=json.loads(p.stdout or p.stderr)
    if p.returncode or not (data.get('ok') is True or data.get('manifest_version')=='v1'):
        raise RuntimeError(json.dumps(data,ensure_ascii=False))
    return data.get('data',data)

def rows(table,fields,stem):
    result=[];offset=0
    while True:
        name=stem+'-'+str(offset)+'.ndjson'
        args=['--offset',str(offset),'--format','ndjson','--output','artifacts/'+name,'--overwrite']
        for field in fields:args+=['--field-id',field]
        manifest=call('+record-list',*args,table=table)
        page=[json.loads(line) for line in (ROOT/'artifacts'/name).read_text().splitlines() if line.strip()]
        if len(page)!=manifest['records_count']:raise RuntimeError('Incomplete records artifact')
        result.extend(page)
        if manifest['has_more'] is False:return result
        if not page:raise RuntimeError('Pagination stalled')
        offset+=len(page)

def create_records(table,values):
    for start in range(0,len(values),200):
        result=call('+record-batch-create',table=table,body={'create_records':values[start:start+200]})
        if len(result.get('record_id_list',[]))!=len(values[start:start+200]):raise RuntimeError('Unconfirmed record creation')

def ensure_calendar(state):
    table=state['dashboard']['period_table_id']
    existing=rows(table,['周期编号'],'dashboard-calendar')
    keys={row['周期编号'] for row in existing}
    today=dt.datetime.now(TZ).date()
    dates=[dt.date.fromisoformat(item['source_time'][:10]) for item in state['items'] if item.get('source_time')]
    first=min(dates+[today])
    until=today+dt.timedelta(days=93)
    values=[]
    for kind,step in [('日',1),('周',7)]:
        current=first if kind=='日' else first-dt.timedelta(days=first.weekday())
        while current<=until:
            key=('D:' if kind=='日' else 'W:')+current.isoformat()
            if key not in keys:
                end=current+dt.timedelta(days=step)
                values.append({'周期编号':key,'周期类型':[kind],'周期开始':current.isoformat()+'T00:00:00+08:00',
                               '周期结束':end.isoformat()+'T00:00:00+08:00',
                               '周期标签':current.isoformat()+(' 当周' if kind=='周' else '')})
            current+=dt.timedelta(days=step)
    if values:create_records(table,values)
    return len(values)

if __name__=='__main__':
    state=json.loads((ROOT/'state.json').read_text())
    print(json.dumps({'ok':True,'new_calendar_rows':ensure_calendar(state)},ensure_ascii=False))
