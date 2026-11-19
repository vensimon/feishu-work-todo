"""Read authorized meeting artifacts and mention context; never assign or finish work."""
import hashlib
import html
import datetime as dt
import json
import pathlib
import re
import urllib.parse

DEFAULT_BOTS=['云文档助手','多维表格助手','智能纪要助手']
MENTION=re.compile(r'提及.{0,3}你|@.{0,2}你|mentioned you|mentioned_you|在.{0,20}(文档|表格|评论).{0,10}提及',re.I)
MEETING=re.compile(r'会议纪要|智能纪要|妙记|会议日报|meeting notes|minutes/',re.I)

def settings(state):
    return {'enabled':True,'notification_chat_ids':[],'notification_bot_names':DEFAULT_BOTS,
            'minutes_enabled':True,'meeting_search_enabled':True,**state.get('source_settings',{})}

def notification_chat(chat,state):
    config=settings(state)
    return bool(config['enabled'] and chat.get('chat_mode')=='p2p' and chat.get('p2p_target_type')=='bot' and
                (chat['chat_id'] in config['notification_chat_ids'] or chat.get('name') in config['notification_bot_names']))

def mentioned(message,owner):
    return bool(MENTION.search(message.get('content') or '') or
                any(m.get('id')==owner or m.get('open_id')==owner for m in message.get('mentions',[])))

def links(message):
    text=html.unescape(message.get('content') or '')
    result=[]
    for raw in re.findall(r'https://[^\s<>"\]\)]+',text):
        try:p=urllib.parse.urlsplit(raw)
        except ValueError:continue
        if p.username or p.password or not p.hostname:continue
        if not any(p.hostname==host or p.hostname.endswith('.'+host) for host in ['feishu.cn','larksuite.com','larkoffice.com','doubao.com']):continue
        if re.match(r'^/(docx|wiki|minutes|base)/[A-Za-z0-9]+',p.path) and not p.path.startswith('/wiki/space/'):
            if raw not in result:result.append(raw)
    return result

def source_id(kind,value):return kind+':'+value
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
def event_time(value):
    stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))

def collect(folder,root,messages,state,start,end,call,guard=lambda:None):
    """Keep original responses and per-source failures so an AI can review every item."""
    folder=pathlib.Path(folder);root=pathlib.Path(root);artifacts=folder/'sources';artifacts.mkdir(exist_ok=True)
    config=settings(state);receipts={};coverage={};visited={}
    if not config['enabled']:return {}
    def window(kind):
        value=state.get('source_watermarks',{}).get(kind)
        return dt.datetime.fromisoformat(value)-dt.timedelta(hours=48) if value else start
    def request(args):
        guard();response=call(args,cwd=root);guard()
        if response.get('ok') is False:raise RuntimeError(str(response.get('error',{})))
        return response.get('data',response)
    def pages(args,field):
        found=[];cursor=None
        while True:
            data=request(args+(['--page-token',cursor] if cursor else []))
            found.extend(data.get(field,[]))
            if data.get('has_more') is False:return found
            next_cursor=data.get('page_token')
            if not next_cursor or next_cursor==cursor:raise RuntimeError('Source pagination was incomplete or stalled')
            cursor=next_cursor
    def record(kind,key,url,title='',time=None,**extra):
        sid=source_id(kind,key)
        row={'source_id':sid,'kind':kind,'id':key,'url':url,'title':title,'time':time,
             'evidence_directory':str(folder.resolve()),**extra}
        receipts[sid]=row
        return row
    def artifact(row,data):
        path=artifacts/(hashlib.sha256(row['source_id'].encode()).hexdigest()[:20]+'.json')
        write(path,data);row['evidence_file']=str(path.relative_to(folder));row['evidence_digest']=digest(data)
    def document(url,kind='docx',key=None):
        token=urllib.parse.urlsplit(url).path.rstrip('/').split('/')[-1]
        sid=source_id(kind,key or token)
        if sid in visited:return visited[sid]
        row=record(kind,key or token,url,status='unread');visited[sid]=row
        try:
            data=request(['docs','+fetch','--as','user','--doc',url,'--doc-format','markdown','--detail','with-ids'])
            artifact(row,data);doc=data['document']
            row.update(status='read',title=doc.get('title') or row['title'])
            comments=doc.get('reference_map',{}).get('comments',{})
            if comments.get('tips'):
                row.update(status='context_missing',error='Comments are truncated; read the targeted comment and replies before deciding responsibility')
            if doc.get('tips'):row['context_warning']=doc['tips']
        except Exception as error:guard();row.update(status='unavailable',error=str(error))
        return row
    def minute(token,url,title='',time=None):
        sid=source_id('minutes',token)
        if sid in visited:return visited[sid]
        row=record('minutes',token,url,title,time,status='unread');visited[sid]=row
        try:
            output=str((artifacts/'minutes').relative_to(root))
            data=request(['minutes','+detail','--as','user','--minute-tokens',token,'--todo','--transcript','--output-dir',output])
            artifact(row,data);detail=next(m for m in data['minutes'] if m['minute_token']==token)
            row['title']=detail.get('title') or title
            file=detail.get('artifacts',{}).get('transcript_file')
            if not file:raise RuntimeError('No original transcript returned; AI todos alone do not establish a personal duty')
            path=pathlib.Path(file);path=path if path.is_absolute() else root/path
            if not path.is_file():raise RuntimeError('Reported transcript file is missing')
            if folder.resolve() not in path.resolve().parents:raise RuntimeError('Transcript is outside this scan')
            text=path.read_text();row['transcript_file']=str(path.relative_to(folder))
            row['transcript_digest']=hashlib.sha256(text.encode()).hexdigest()
            stamp=re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)',text)
            if stamp:row['time']=stamp.group(1).replace(' ','T')+'+08:00'
            row['status']='read'
        except Exception as error:guard();row.update(status='unavailable',error=str(error))
        return row
    def base_record(url):
        p=urllib.parse.urlsplit(url);query=urllib.parse.parse_qs(p.query)
        token=p.path.rstrip('/').split('/')[-1];table=(query.get('table') or [''])[0]
        rid=(query.get('record') or query.get('recordId') or query.get('record_id') or [''])[0]
        row=record('base_record',token+'/'+table+'/'+rid,url,status='context_missing')
        if not table or not rid:
            row['error']='Notification links a table, not a specific record; resolve the mentioned row before assigning work'
            return row
        try:
            data=request(['base','+record-get','--as','user','--base-token',token,'--table-id',table,'--record-id',rid,'--format','json'])
            artifact(row,data);row.update(status='read',table_id=table,record_id=rid)
        except Exception as error:guard();row.update(status='unavailable',error=str(error))
        return row
    def expand(url):
        p=urllib.parse.urlsplit(url);kind=p.path.split('/')[1];token=p.path.split('/')[2]
        if kind=='minutes':return minute(token,url)
        if kind=='base':return base_record(url)
        return document(url)

    for message in messages:
        notification=message.get('notification_source')
        is_mention=mentioned(message,state['recipient_open_id'])
        is_meeting=bool(MEETING.search(message.get('content') or ''))
        if not (notification or is_mention or is_meeting):continue
        urls=links(message)
        if not notification and not urls:continue
        row=record('notification',message['message_id'],message.get('message_app_link'),
                   (message.get('content') or '')[:100],message.get('create_time'),
                   status='read',message_id=message['message_id'],chat_id=message['chat_id'],
                   notification_source=notification,mentions_owner=is_mention,resource_ids=[])
        artifact(row,message)
        if not re.sub(r'<[^>]+>|\s','',message.get('content') or ''):
            row.update(status='context_missing',error='Notification card content is empty')
        # Permission-change notices remain evidence, but do not trigger unrelated document reads.
        if is_mention or is_meeting:
            for url in urls:
                if '/base/' in urllib.parse.urlsplit(url).path and not is_mention:continue
                resource=expand(url);row['resource_ids'].append(resource['source_id'])

    if config['minutes_enabled']:
        try:
            found={}
            for flag in ['--participant-ids','--owner-ids']:
                rows=pages(['minutes','+search','--as','user',flag,state['recipient_open_id'],
                            '--start',window('minutes').isoformat(),'--end',end.isoformat(),'--page-size','30'],'items')
                for row in rows:found[row['token']]=row
            for token,data in found.items():
                url=data.get('meta_data',{}).get('app_link')
                minute(token,url,data.get('display_info','').split('\n')[0])
            coverage['minutes']={'complete':True,'discovered':len(found)}
        except Exception as error:guard();coverage['minutes']={'complete':False,'error':str(error)}
    if config['meeting_search_enabled']:
        try:
            meetings=pages(['vc','+search','--as','user','--participant-ids',state['recipient_open_id'],
                            '--start',window('meetings').isoformat(),'--end',end.isoformat(),'--page-size','30'],'items')
            for i in range(0,len(meetings),50):
                ids=','.join(m['id'] for m in meetings[i:i+50])
                details=request(['vc','+detail','--as','user','--meeting-ids',ids])
                if not isinstance(details.get('meetings'),list):raise RuntimeError('Unrecognized meeting details; preserve a pending source')
                for meeting in details.get('meetings',[]):
                    nid=meeting.get('note_id')
                    if nid:
                        note=request(['note','+detail','--as','user','--note-id',nid])
                        token=note.get('note_doc_token')
                        if token:
                            meta=request(['drive','metas','batch_query','--as','user','--data',json.dumps({'request_docs':[{'doc_type':'docx','doc_token':token}],'with_url':True})])
                            url=next(m['url'] for m in meta['metas'] if m.get('doc_token')==token)
                            document(url,'note',nid)
            coverage['meetings']={'complete':True,'discovered':len(meetings)}
        except Exception as error:guard();coverage['meetings']={'complete':False,'error':str(error)}
    coverage['notifications']={'complete':True,'discovered':sum(bool(m.get('notification_source')) for m in messages)}
    for key,result in coverage.items():
        if not result['complete']:
            record('coverage',key,None,status='unavailable',title=key,error=result['error'])
    for old in state.get('source_candidates',[]):
        if old['source_id'] in receipts:continue
        if old['kind']=='coverage' and coverage.get(old['id'],{}).get('complete'):
            record('coverage',old['id'],None,status='read',title='来源读取已恢复')
        elif old['kind'] in ['docx','minutes','base_record'] and old.get('url'):
            expand(old['url'])
    previous={r['source_id']:r for r in state.get('source_candidates',[])}
    previous.update(receipts)
    output={'start':start.isoformat(),'through':end.isoformat(),'coverage':coverage,'sources':list(previous.values())}
    write(folder/'source-evidence.json',output)
    write(folder/'source-ledger-template.json',[{'source_id':r['source_id'],'decision':None,'reason':'','item_keys':[]} for r in previous.values()])
    return {'source_evidence_file':str(folder/'source-evidence.json'),'source_ledger_template':str(folder/'source-ledger-template.json'),
            'source_candidates':len(previous),'source_coverage':coverage}

def validate_ledger(folder,ledger_file,state):
    folder=pathlib.Path(folder);payload=json.loads((folder/'source-evidence.json').read_text())
    sources={r['source_id']:r for r in payload['sources']}
    check_artifacts(payload,folder)
    raw=pathlib.Path(ledger_file).read_bytes();ledger=json.loads(raw)
    if not isinstance(ledger,list) or len({r['source_id'] for r in ledger})!=len(ledger):raise ValueError('Source ledger must contain unique source dispositions')
    if {r['source_id'] for r in ledger}!=set(sources):raise ValueError('Every meeting and notification source needs a disposition')
    tasks={i['key']:i for i in state['items']};pending=[]
    for row in ledger:
        source=sources[row['source_id']];decision=row.get('decision')
        if not row.get('reason'):raise ValueError('Explain each source disposition')
        if source['status']!='read' and decision!='needs_confirmation':raise ValueError('Unread source must remain pending, not silently excluded')
        if decision=='task':
            keys=row.get('item_keys') or ([row['item_key']] if row.get('item_key') else [])
            if not keys:raise ValueError('Source-derived work must point to a real pending task')
            for key in keys:
                item=tasks.get(key,{})
                if not item.get('base_record_id') or item.get('completed') or item.get('base_record_missing'):raise ValueError('Do not reopen a completed prior task from source evidence')
        elif decision=='needs_confirmation':
            label=row.get('label')
            if not label or len(label)>60:raise ValueError('Pending source needs a concise label')
            pending.append({**source,'label':label,'reason':row['reason']})
        elif decision=='exclude':
            if row.get('reason_code') not in ['informational_only','unrelated_to_user','not_actionable','already_recorded','recorded_completion']:
                raise ValueError('Use a concrete, evidence-backed exclusion reason')
            if row['reason_code']=='already_recorded' and row.get('item_key') not in tasks:
                raise ValueError('An existing-work exclusion must name the actual registered task')
            if row['reason_code']=='recorded_completion':
                item=tasks.get(row.get('item_key'),{})
                if not item.get('completed') or not item.get('base_completed_at'):raise ValueError('A historical mention is not proof of completion')
                if not source.get('time'):raise ValueError('Need source time to distinguish a new round from an old completion')
                if event_time(item['base_completed_at'])<event_time(source['time']):raise ValueError('An older completion cannot close a newer source')
        else:raise ValueError('Unknown source disposition')
    report={'status':'validated','through':payload['through'],'source_digest':digest(payload),
            'ledger_file':str(pathlib.Path(ledger_file).resolve()),'ledger_digest':hashlib.sha256(raw).hexdigest(),
            'pending_sources':pending,'coverage':payload['coverage'],'counts':{d:sum(r['decision']==d for r in ledger) for d in ['task','exclude','needs_confirmation']}}
    state['source_audit']=report;state['source_candidates']=pending
    state.setdefault('source_watermarks',{}).update({k:payload['through'] for k,v in payload['coverage'].items() if v['complete']})
    return report

def check_artifacts(payload,folder):
    for source in payload['sources']:
        if source['status']!='read':continue
        base=pathlib.Path(source.get('evidence_directory') or folder)
        if source.get('evidence_file'):
            data=json.loads((base/source['evidence_file']).read_text())
            if digest(data)!=source['evidence_digest']:raise ValueError('Source evidence changed after collection')
        if source.get('transcript_file'):
            raw=(base/source['transcript_file']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=source['transcript_digest']:raise ValueError('Meeting transcript changed after collection')

def require_audit(folder,state):
    path=pathlib.Path(folder)/'source-evidence.json'
    if not path.exists():return
    payload=json.loads(path.read_text());audit=state.get('source_audit',{})
    check_artifacts(payload,path.parent)
    if audit.get('status')!='validated' or audit.get('through')!=payload['through'] or audit.get('source_digest')!=digest(payload):
        raise RuntimeError('Review meeting and notification sources before completing this scan')
    if hashlib.sha256(pathlib.Path(audit['ledger_file']).read_bytes()).hexdigest()!=audit.get('ledger_digest'):
        raise RuntimeError('Source decisions changed after review')
