"""Initialization and agent-facing operations for a self-owned installation."""
import argparse
import datetime as dt
import json
import pathlib
import runpy
import shutil
import subprocess
import sys
from runtime_paths import ROOT,PROFILE,CLI,current_identity,assert_identity,prepare_storage,write_state,cli_json
from online_config import CLIENT_VERSION,get_config
from assistant_control import require_enabled,read_control,set_enabled,run_guarded

SCRIPTS=pathlib.Path(__file__).resolve().parent
PACKAGE=SCRIPTS.parent

def load():
    state=json.loads((ROOT/'state.json').read_text())
    assert_identity(state)
    return state

def doctor():
    result={'skill_version':CLIENT_VERSION,'storage':str(ROOT),'cli_profile':PROFILE,'cli_found':bool(shutil.which(CLI)),
            'initialized':(ROOT/'state.json').exists(),'callback_connected':False,'host_schedule_verified':False,
            'assistant_enabled':read_control()['enabled']}
    try:
        identity=current_identity();result['authorized_as']=identity['recipient_name']
        if result['initialized']:
            s=load();result['base_url']=s['base']['url']
            result['host_schedule_verified']=bool(s.get('host_schedule',{}).get('verified'))
            f=ROOT/'card-service-status.json'
            status=json.loads(f.read_text()) if f.exists() else {}
            if status.get('ready'):
                for key in ['pid','consumer_pid']:os_kill(status[key])
                result['callback_connected']=True
    except Exception as error:result['attention']=str(error)
    print(json.dumps(result,ensure_ascii=False,indent=2))

def os_kill(pid):
    import os
    os.kill(int(pid),0)

def init(confirm):
    if not confirm:raise RuntimeError('Initialization creates your own Base and statistics workflows; use --confirm after reviewing the logged-in identity')
    identity=current_identity();prepare_storage()
    if (ROOT/'state.json').exists():
        state=load()
    else:
        schema=json.loads((PACKAGE/'assets/base-schema.json').read_text())
        result=cli_json(['base','+base-create','--as','user','--name','我的工作待办','--time-zone','Asia/Shanghai','--table-name','待办清单',
                         '--fields',json.dumps(schema,ensure_ascii=False)],cwd=ROOT)
        data=result['data'];base=data['base'];table=data['table']
        state={'version':1,**identity,'cli_profile':PROFILE,'cli_path':CLI,'timezone':'Asia/Shanghai',
               'items':[],'sent_runs':[],'last_successful_scan_at':None,'completion_backend':'feishu_base',
               'base':{'base_token':base['base_token'],'table_id':table['id'],'url':base['url'],'fields':{}},
               'setup':{'core_created':True,'host_schedule':False,'callback_roundtrip_verified':False}}
        write_state(state)
    from dashboard_support import call,save
    fields=call('+field-list',table=state['base']['table_id'])['fields']
    names={f['name'] for f in fields}
    formulas=json.loads((PACKAGE/'assets/source-formulas.json').read_text())
    missing=[f for f in formulas if f['name'] not in names]
    if missing:call('+field-create','--i-have-read-guide',table=state['base']['table_id'],body=missing)
    state['base']['fields']={f['name']:f['id'] for f in call('+field-list',table=state['base']['table_id'])['fields']}
    write_state(state)
    runpy.run_path(str(SCRIPTS/'provision_dashboard.py'),run_name='__main__')
    state=json.loads((ROOT/'state.json').read_text());base_token=state['base']['base_token']
    dashboards=call('+dashboard-list')['items']
    found=next((d for d in dashboards if d.get('name')=='工作待办 · 处理与积压仪表盘'),None)
    created=found or call('+dashboard-create','--name','工作待办 · 处理与积压仪表盘')
    save('dashboard-created.json',created)
    runpy.run_path(str(SCRIPTS/'build_dashboard.py'),run_name='__main__')
    state=json.loads((ROOT/'state.json').read_text())
    state['dashboard']['url']=state['base']['url'].split('?')[0]+'?table='+state['dashboard']['dashboard_id']
    configure_views(state)
    state['setup']['base_and_dashboard_ready']=True
    if not (ROOT/'assistant-control.json').exists():set_enabled(False)
    from control_panel import install_entry
    try:state['control_entry']=install_entry()
    except (OSError,ValueError) as error:state['control_entry']={'entry_created':False,'attention':str(error)}
    write_state(state)
    print(json.dumps({'ok':True,'owner':identity['recipient_name'],'base_url':state['base']['url'],
                      'dashboard_url':state['dashboard']['url'],'control_entry':state['control_entry'],
                      'remaining':['configure card.action.trigger for your own app','open personal control panel and enable the receiver','verify callback roundtrip','configure and verify your host scheduler']},ensure_ascii=False))

def configure_views(state):
    from dashboard_support import call
    table=state['base']['table_id'];existing=call('+view-list',table=table)['views']
    by={v['name']:v['id'] for v in existing}
    plans=[('待处理',False,['本人职责','跟进类型']),('已完成',True,['来源月份','事项分类']),
           ('按月份归档',None,['来源月份','事项分类']),('按日期查看',None,['来源日期','本人职责']),
           ('按本人职责',None,['本人职责','跟进类型'])]
    for name,completed,groups in plans:
        if name not in by:
            call('+view-create',table=table,body={'name':name,'type':'grid'})
            by={v['name']:v['id'] for v in call('+view-list',table=table)['views']}
        conditions=[]
        if completed is not None:conditions.append(['处理完毕','==',completed])
        call('+view-set-filter','--view-id',by[name],table=table,body={'logic':'and','conditions':conditions})
        call('+view-set-group','--view-id',by[name],table=table,body={'group_config':[{'field':f,'desc':f=='来源月份'} for f in groups]})
        call('+view-set-sort','--view-id',by[name],table=table,body={'sort_config':[{'field':'截止日期','desc':False},{'field':'来源日期','desc':True}]})
    state['base']['classification_views']=by

def upsert(path):
    generation=require_enabled()
    state=load()
    from dashboard_support import call,rows
    plans=json.loads(pathlib.Path(path).read_text())
    if not isinstance(plans,list):raise ValueError('Proposal must be a JSON array')
    if len({p['key'] for p in plans})!=len(plans):raise ValueError('Duplicate keys in proposal')
    fields=call('+field-list',table=state['base']['table_id'])['fields']
    options={f['name']:{o['name'] for o in f.get('options',[])} for f in fields}
    current=rows(state['base']['table_id'],list(state['base']['fields']),'upsert-current')
    by_key={r.get('事项编号'):r for r in current if r.get('事项编号')}
    old={i['key']:i for i in state['items']};added=changed=0
    for plan in plans:
        require_enabled(generation)
        patch={}
        key=plan['key'];source=plan['source']
        if not isinstance(key,str) or not key or key.startswith('__'):raise ValueError('Use a stable, non-test item key')
        if 'completed' in plan:raise ValueError('Message extraction must never set completion state')
        role=plan.get('role','职责待确认')
        if role not in options['本人职责']:raise ValueError('Add this real responsibility with option-add first: '+role)
        if plan['followup'] not in options['跟进类型']:raise ValueError('Unknown progress state')
        if plan['category'] not in options['事项分类']:raise ValueError('Unknown business category')
        if not source.get('message_id','').startswith('om_') or not source.get('chat_id','').startswith('oc_'):
            raise ValueError('Retain concrete message and conversation evidence')
        day=dt.date.fromisoformat(source['time'][:10]).isoformat()
        summary=plan['summary'].strip()
        if not summary or len(summary)>get_config()['extraction']['summary_max_chars']:raise ValueError('Write a concise notification summary within the configured length')
        data={'事项':plan['title'],'跟进类型':[plan['followup']],'本人职责':[role],'事项分类':[plan['category']],
              '通知摘要':summary,'下一步':plan['next_step'],'日期说明':plan.get('date_note','未明确截止日期'),
              '原消息':source['url'],'来源日期':day+'T00:00:00+08:00','事项编号':key}
        if plan.get('deadline'):
            data['截止日期']=dt.date.fromisoformat(plan['deadline']).isoformat()+'T00:00:00+08:00'
        if key in by_key:
            row=by_key[key]
            if type(row.get('处理完毕')) is not bool:raise ValueError('Missing completion checkbox')
            if row['处理完毕']:continue
            previous=old.get(key,{}).get('last_generated_fields',{})
            patch={}
            for field,value in data.items():
                if field in ['事项编号','来源日期','原消息']:continue
                actual=row.get(field)
                if (field not in previous and not actual) or actual==previous.get(field):patch[field]=value
            if patch:
                call('+record-batch-update',table=state['base']['table_id'],body={'update_records':{row['record_id']:patch}});changed+=1
            rid=row['record_id']
        else:
            if key in old and old[key].get('base_record_id'):
                # Deleted records are tombstones, not missing work to recreate.
                continue
            data['处理完毕']=False
            result=call('+record-batch-create',table=state['base']['table_id'],body={'create_records':[data]})
            rid=result['record_id_list'][0];added+=1
        prior=old.get(key,{})
        generated={**prior.get('last_generated_fields',{}),**(patch if key in by_key else data)}
        old[key]={**prior,'key':key,'title':plan['title'],'base_record_id':rid,'source_time':prior.get('source_time') or source['time'],
                  'chat_id':prior.get('chat_id') or source['chat_id'],'message_id':prior.get('message_id') or source['message_id'],
                  'message_app_link':prior.get('message_app_link') or source['url'],'latest_evidence':source,
                  'execution_owner':plan.get('execution_owner'),'last_generated_fields':generated}
        by_key[key]={**by_key.get(key,{}),'record_id':rid,**(patch if key in by_key else data)}
        state['items']=list(old.values());write_state(state)
    subprocess.run([sys.executable,str(SCRIPTS/'sync_base_status.py')],check=True)
    print(json.dumps({'ok':True,'added':added,'updated':changed},ensure_ascii=False))

def option_add(field,name,confirm):
    state=load()
    if not confirm:raise ValueError('Confirm the exact additional classification with --confirm')
    if field not in ['本人职责','事项分类']:raise ValueError('Only responsibility/category options can be appended')
    from dashboard_support import call
    definition=call('+field-get','--field-id',state['base']['fields'][field],table=state['base']['table_id'])['field']
    if definition['type']!='select' or definition.get('multiple') is not False:raise ValueError('Unexpected field definition')
    if any(o['name']==name for o in definition['options']):return
    body={k:v for k,v in definition.items() if k in ['name','type','multiple','description','options','default_value']}
    body['options']=[*body['options'],{'name':name,'hue':'Gray','lightness':'Lighter'}]
    call('+field-update','--field-id',definition['id'],'--yes',table=state['base']['table_id'],body=body)
    print(json.dumps({'ok':True,'appended':name},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('doctor');a=sub.add_parser('init');a.add_argument('--confirm',action='store_true')
    a=sub.add_parser('upsert');a.add_argument('file')
    a=sub.add_parser('option-add');a.add_argument('--field',required=True);a.add_argument('--name',required=True);a.add_argument('--confirm',action='store_true')
    a=sub.add_parser('finish-scan');a.add_argument('--through',required=True)
    a.add_argument('--evidence-dir',required=True);a.add_argument('--review-ledger',required=True)
    a=sub.add_parser('schedule-record');a.add_argument('--host',required=True);a.add_argument('--job-id',required=True)
    args=parser.parse_args()
    if args.cmd=='doctor':doctor()
    elif args.cmd=='init':init(args.confirm)
    elif args.cmd=='upsert':upsert(args.file)
    elif args.cmd=='option-add':option_add(args.field,args.name,args.confirm)
    elif args.cmd=='finish-scan':
        require_enabled()
        state=load();dt.datetime.fromisoformat(args.through)
        from review_audit import finish
        report=finish(args.evidence_dir,args.review_ledger,args.through,state)
        state['last_successful_scan_at']=args.through;write_state(state)
        print(json.dumps({'ok':True,'review_audit':report['counts'],'pending_review_clues':len(report['pending_candidates'])},ensure_ascii=False))
    elif args.cmd=='schedule-record':
        state=load();state['host_schedule']={'host':args.host,'job_id':args.job_id,'verified':True};write_state(state)

if __name__=='__main__':run_guarded(main)
