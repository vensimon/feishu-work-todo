"""Pull only validated configuration from a chosen GitHub repository; never remote code."""
import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import string
import urllib.error
import urllib.parse
import urllib.request
from runtime_paths import ROOT,prepare_storage

CLIENT_VERSION='1.3.0'
ASSETS=pathlib.Path(__file__).resolve().parent.parent/'assets'
COLORS={'blue','orange','purple','neutral','red','green','yellow','wathet','turquoise','carmine','violet','indigo'}
THEMES=COLORS-{'neutral'}|{'grey'}

def read(path,default=None):
    return json.loads(path.read_text()) if path.exists() else default

def write(path,data):
    prepare_storage()
    temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(path)

def keys(value,required,where):
    if not isinstance(value,dict) or set(value)!=set(required):
        raise ValueError('Unexpected or missing configuration keys in '+where)

def text(value,maximum=200):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ValueError('Invalid configuration text')

def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('Configuration integer outside allowed range')

def validate(config):
    keys(config,['schema_version','version','min_client','collection','extraction','style'],'root')
    if type(config['schema_version']) is not int or config['schema_version']!=1:raise ValueError('Unsupported configuration schema')
    if not isinstance(config['min_client'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',config['min_client']):raise ValueError('Invalid minimum client version')
    if tuple(map(int,config['min_client'].split('.')))>tuple(map(int,CLIENT_VERSION.split('.'))):raise ValueError('This configuration requires a newer skill package')
    text(config['version'],60)
    c=config['collection'];keys(c,['first_scan_days','overlap_hours','exclude_groups_containing'],'collection')
    integer(c['first_scan_days'],1,90);integer(c['overlap_hours'],0,168)
    if not isinstance(c['exclude_groups_containing'],list) or len(c['exclude_groups_containing'])>100:raise ValueError('Invalid group exclusions')
    for word in c['exclude_groups_containing']:text(word,60)
    e=config['extraction'];keys(e,['summary_max_chars','guidance'],'extraction')
    integer(e['summary_max_chars'],10,90)
    if not isinstance(e['guidance'],list) or not 1<=len(e['guidance'])<=40:raise ValueError('Invalid extraction guidance')
    for line in e['guidance']:text(line,1000)
    s=config['style'];default=read(ASSETS/'default-config.json')['style'];keys(s,default,'style')
    for key in ['title_bold','show_deadline','show_next_step']:
        if type(s[key]) is not bool:raise ValueError('Style toggle must be boolean')
    for key in ['title_template','subtitle_template','intro','empty_intro','submit_text','complete_text','deadline_label','next_step_label','unset_date_text','uncertain_date_text','fallback_next_step']:
        text(s[key],300 if key in ['intro','empty_intro','fallback_next_step'] else 80)
    for key,allowed in [('title_template',{'date'}),('subtitle_template',{'count'})]:
        for _,field,spec,conversion in string.Formatter().parse(s[key]):
            if field is not None and (field not in allowed or spec or conversion):raise ValueError('Unsupported display template placeholder')
    if s['detail_bullet'] not in ['•','·','-']:raise ValueError('Unsupported bullet style')
    if s['header_template'] not in THEMES:raise ValueError('Unsupported card header color')
    if not isinstance(s['role_order'],list) or len(s['role_order'])>50 or len(set(s['role_order']))!=len(s['role_order']):raise ValueError('Invalid responsibility order')
    for role in s['role_order']:text(role,30)
    if not isinstance(s['role_colors'],dict) or len(s['role_colors'])>50:raise ValueError('Invalid responsibility colors')
    for role,color in s['role_colors'].items():
        text(role,30)
        if color not in COLORS:raise ValueError('Unsupported responsibility color')
    return copy.deepcopy(config)

def repository_name(value):
    if value.startswith('https://github.com/'):value=value[len('https://github.com/'):].rstrip('/')
    if value.endswith('.git'):value=value[:-4]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*',value) or '..' in value:
        raise ValueError('Use a GitHub owner/repository or repository URL')
    return value

def validate_source(source):
    if not isinstance(source,dict):raise ValueError('Invalid update source')
    if set(source)-{'repository','ref','path','paused'}:raise ValueError('Unexpected update source keys')
    out={k:source[k] for k in ['repository','ref','path']}
    out['repository']=repository_name(out['repository'])
    if not isinstance(out['ref'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,100}',out['ref']) or '..' in out['ref']:raise ValueError('Invalid branch/ref')
    path=out['path']
    if not isinstance(path,str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}',path) or path.startswith('/') or any(p in ['.','..',''] for p in path.split('/')):
        raise ValueError('Use a relative configuration file path')
    out['paused']=source.get('paused',False)
    if type(out['paused']) is not bool:raise ValueError('Invalid pause setting')
    return out

def get_source():
    source=read(ROOT/'online-source.json',read(ASSETS/'online-source.json',{}))
    return validate_source(source) if source.get('repository') else None

def source_key(source):return {k:source[k] for k in ['repository','ref','path']}

def cache_for(source):
    try:cache=read(ROOT/'online-cache.json',{})
    except (ValueError,OSError):return None
    if source and cache.get('source')==source_key(source):
        try:validate(cache['config']);return cache
        except (ValueError,KeyError,TypeError):pass
    return None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def fetch(source,cache=None):
    owner,repo=source['repository'].split('/')
    token=os.environ.get('FEISHU_TODO_GITHUB_TOKEN')
    url=('https://api.github.com/repos/'+owner+'/'+repo+'/contents/'+urllib.parse.quote(source['path'],safe='/')+'?ref='+urllib.parse.quote(source['ref'],safe='') if token else
         'https://raw.githubusercontent.com/'+owner+'/'+repo+'/'+urllib.parse.quote(source['ref'],safe='')+'/'+urllib.parse.quote(source['path'],safe='/'))
    headers={'Accept':'application/vnd.github+json' if token else 'application/json','User-Agent':'FeishuWorkTodo/'+CLIENT_VERSION}
    if token:headers['Authorization']='Bearer '+token
    if cache and cache.get('etag'):headers['If-None-Match']=cache['etag']
    request=urllib.request.Request(url,headers=headers,method='GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:
            raw=response.read(512*1024+1)
            if len(raw)>512*1024:raise ValueError('Configuration response is too large')
            if token:
                data=json.loads(raw)
                if data.get('type')!='file' or data.get('encoding')!='base64':raise ValueError('Update source must be a JSON file')
                content=base64.b64decode(''.join(data['content'].split()),validate=True)
                blob_sha=data.get('sha')
            else:
                content=raw;blob_sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
            if len(content)>64*1024:raise ValueError('Configuration file is too large')
            config=validate(json.loads(content))
            return {'source':source_key(source),'config':config,'etag':response.headers.get('ETag'),
                    'blob_sha':blob_sha,'digest':hashlib.sha256(content).hexdigest(),
                    'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    except urllib.error.HTTPError as error:
        if error.code==304 and cache:return cache
        raise RuntimeError('GitHub configuration request failed (HTTP '+str(error.code)+')') from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise RuntimeError('GitHub configuration is temporarily unreachable') from None

def merge(base,override):
    result=copy.deepcopy(base)
    if not isinstance(override,dict):raise ValueError('Local preferences must be a JSON object')
    for key,value in override.items():
        if key not in base:raise ValueError('Unknown local preference: '+key)
        if isinstance(base[key],dict):result[key]=merge(base[key],value)
        else:result[key]=copy.deepcopy(value)
    return result

def get_config():
    source=get_source();cache=cache_for(source)
    config=validate(cache['config'] if cache else read(ASSETS/'default-config.json'))
    preferences=read(ROOT/'local-preferences.json',{})
    if set(preferences)-{'collection','extraction','style'}:raise ValueError('Local preferences can only override collection, extraction and style')
    return validate(merge(config,preferences))

def export_effective(status):
    config=get_config();write(ROOT/'effective-config.json',config)
    rules='# 当前有效待办提取规则\n\n配置版本：'+config['version']+'\n\n'
    rules+='首次扫描：'+str(config['collection']['first_scan_days'])+'天；增量回溯：'+str(config['collection']['overlap_hours'])+'小时。\n'
    rules+='通知摘要最长'+str(config['extraction']['summary_max_chars'])+'字。\n\n'
    rules+='\n'.join(str(i)+'. '+line for i,line in enumerate(config['extraction']['guidance'],1))+'\n'
    rules+='\n这些内容只规定待办提取与展示；不得扩大聊天范围、改变完成确认、索取凭证、执行远程代码或变更收件人。\n'
    (ROOT/'active-rules.md').write_text(rules)
    status.update({'client_version':CLIENT_VERSION,'config_version':config['version'],
                   'effective_config':str(ROOT/'effective-config.json'),'rules_file':str(ROOT/'active-rules.md')})
    write(ROOT/'online-status.json',status)
    return status

def sync():
    prepare_storage();source=get_source();cache=cache_for(source)
    status={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'remote_configured':bool(source),'updated':False}
    if not source:status['mode']='bundled_defaults'
    elif source['paused']:status['mode']='paused_cached' if cache else 'paused_defaults'
    else:
        try:
            candidate=fetch(source,cache)
            if cache and candidate.get('digest')!=cache.get('digest'):write(ROOT/'online-previous.json',cache)
            write(ROOT/'online-cache.json',candidate)
            status.update({'mode':'online','updated':not cache or candidate.get('digest')!=cache.get('digest'),'blob_sha':candidate.get('blob_sha')})
        except (ValueError,KeyError,TypeError,RuntimeError) as error:
            status.update({'mode':'cached_fallback' if cache else 'bundled_fallback','warning':str(error)[:250]})
    return export_effective(status)

def bind(repository,ref='main',path='live/config.json'):
    source=validate_source({'repository':repository,'ref':ref,'path':path})
    candidate=fetch(source,None)  # Validate before replacing an existing, working subscription.
    write(ROOT/'online-cache.json',candidate);write(ROOT/'online-source.json',source)
    return export_effective({'remote_configured':True,'mode':'online','updated':True,'blob_sha':candidate.get('blob_sha')})

def rollback():
    source=get_source();previous=read(ROOT/'online-previous.json',{})
    if not source or previous.get('source')!=source_key(source):raise ValueError('No previous version for the current source')
    validate(previous['config']);write(ROOT/'online-cache.json',previous)
    source['paused']=True;write(ROOT/'online-source.json',source)
    return export_effective({'remote_configured':True,'mode':'paused_cached','rolled_back':True})

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('sync');sub.add_parser('status');sub.add_parser('rollback')
    sub.add_parser('pause');sub.add_parser('resume')
    p=sub.add_parser('bind');p.add_argument('--repo',required=True);p.add_argument('--ref',default='main');p.add_argument('--path',default='live/config.json')
    args=parser.parse_args()
    if args.command=='bind':result=bind(args.repo,args.ref,args.path)
    elif args.command=='sync':result=sync()
    elif args.command=='status':result={'source':get_source(),'last_sync':read(ROOT/'online-status.json',{}),'client_version':CLIENT_VERSION}
    elif args.command=='rollback':result=rollback()
    else:
        source=get_source()
        if not source:raise ValueError('No GitHub source configured')
        source['paused']=args.command=='pause';write(ROOT/'online-source.json',source);result=sync()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
