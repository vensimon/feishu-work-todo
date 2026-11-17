"""A personal loopback control panel, opened from a double-clickable local entry."""
import argparse
import hmac
import http.server
import json
import os
import pathlib
import secrets
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from runtime_paths import ROOT,PROFILE,prepare_storage
from assistant_control import read_control,set_enabled
from online_config import CLIENT_VERSION,NoRedirect
import service

ASSETS=pathlib.Path(__file__).resolve().parent.parent/'assets'
CHANGE_LOCK=threading.Lock()

def read(path,default=None):
    try:return json.loads(path.read_text()) if path.exists() else default
    except (ValueError,OSError):return default

def live(pid):
    try:os.kill(int(pid),0);return True
    except (OSError,ValueError,TypeError):return False

def get_status():
    state=read(ROOT/'state.json',{});control=read_control();receiver=read(ROOT/'card-service-status.json',{})
    connected=bool(receiver.get('ready') and live(receiver.get('pid')) and live(receiver.get('consumer_pid')))
    cache=read(ROOT/'online-cache.json',{})
    return {'initialized':bool(state.get('recipient_open_id') and state.get('application_id')),
            'enabled':control['enabled'],'receiver_connected':connected,'client_version':CLIENT_VERSION,
            'receiver_version':receiver.get('service_version'),
            'owner_name':state.get('recipient_name',''),'schedule_registered':bool(state.get('host_schedule',{}).get('verified')),
            'callback_verified':bool(state.get('setup',{}).get('callback_roundtrip_verified')),
            'config_version':cache.get('config',{}).get('version','内置默认'),
            'switch_error':control.get('error'),
            'base_url':safe_feishu_url(state.get('base',{}).get('url')),
            'dashboard_url':safe_feishu_url(state.get('dashboard',{}).get('url'))}

def safe_feishu_url(url):
    from urllib.parse import urlsplit
    if not isinstance(url,str):return None
    parts=urlsplit(url)
    if parts.scheme=='https' and parts.hostname and parts.hostname.endswith(('.feishu.cn','.larksuite.com')) and not parts.username:return url
    return None

def change_enabled(enabled):
    if type(enabled) is not bool:raise ValueError('开关值必须为true或false。')
    with CHANGE_LOCK:
        state=read(ROOT/'state.json',{})
        if enabled and not state.get('recipient_open_id'):raise ValueError('请先让AI完成本人授权与待办助手初始化。')
        before=get_status()
        if enabled and before['enabled'] and before['receiver_connected'] and before['receiver_version']==CLIENT_VERSION:
            return {'ok':True,'message':'助手已开启。','status':before}
        set_enabled(enabled)
        try:
            if state:
                if enabled:service.install(state)
                else:service.stop(state)
        except Exception as error:
            if enabled:set_enabled(False)
            return {'ok':False,'message':('开启失败，助手保持关闭。' if enabled else '已禁止扫描、发送和保存，但接收进程停止未确认，请重试关闭。'),
                    'detail':str(error)[:250],'status':get_status()}
        if enabled:
            for _ in range(10):
                if get_status()['receiver_connected']:break
                time.sleep(0.2)
        return {'ok':True,'message':'助手已开启。' if enabled else '助手已关闭，全部待办与历史记录保留。','status':get_status()}

class Handler(http.server.BaseHTTPRequestHandler):
    server_version='TodoControl'
    def log_message(self,*args):pass
    def reply(self,code,body,content_type='application/json; charset=utf-8'):
        if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers();self.wfile.write(body)
    def allowed_host(self):return self.headers.get('Host')==self.server.allowed_host
    def authorized(self):
        origin=self.headers.get('Origin')
        token=self.headers.get('X-Control-Token','')
        return self.allowed_host() and (not origin or origin==self.server.origin) and hmac.compare_digest(token,self.server.token)
    def do_GET(self):
        self.server.last_request=time.monotonic()
        if not self.allowed_host():self.reply(403,{'error':'Host refused'});return
        if self.path=='/':self.reply(200,(ASSETS/'control-panel.html').read_bytes(),'text/html; charset=utf-8');return
        if not self.authorized():self.reply(403,{'error':'请从本机控制台入口打开。'});return
        if self.path=='/api/status':self.reply(200,get_status())
        else:self.reply(404,{'error':'Not found'})
    def do_POST(self):
        self.server.last_request=time.monotonic()
        if not self.authorized():self.reply(403,{'error':'Request refused'});return
        if self.path!='/api/control':self.reply(404,{'error':'Not found'});return
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.reply(415,{'error':'JSON required'});return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=100:raise ValueError('Invalid request size')
            value=json.loads(self.rfile.read(size))
            if not isinstance(value,dict) or set(value)!={'enabled'}:raise ValueError('Only the local switch is supported')
            self.reply(200,change_enabled(value['enabled']))
        except (ValueError,TypeError) as error:self.reply(400,{'error':str(error)})

def create_server():
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True;server.token=secrets.token_urlsafe(32)
    server.allowed_host='127.0.0.1:'+str(server.server_port);server.origin='http://'+server.allowed_host
    server.last_request=time.monotonic()
    return server

def serve():
    prepare_storage();server=create_server()
    info={'pid':os.getpid(),'url':server.origin,'token':server.token,'runtime':str(ROOT)}
    path=ROOT/'control-server.json';temporary=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    temporary.write_text(json.dumps(info));temporary.chmod(0o600);temporary.replace(path)
    def idle_timeout():
        while True:
            time.sleep(30)
            if time.monotonic()-server.last_request>1800:server.shutdown();return
    threading.Thread(target=idle_timeout,daemon=True).start()
    try:server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if read(path,{}).get('pid')==os.getpid():path.unlink(missing_ok=True)

def existing_server():
    info=read(ROOT/'control-server.json',{})
    if not live(info.get('pid')) or info.get('runtime')!=str(ROOT):return None
    from urllib.parse import urlsplit
    parts=urlsplit(info.get('url',''))
    if parts.scheme!='http' or parts.hostname!='127.0.0.1' or not parts.port or parts.path:return None
    try:
        request=urllib.request.Request(info['url']+'/api/status',headers={'X-Control-Token':info['token']})
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=1) as response:
            if response.status==200:return info
    except (OSError,ValueError,KeyError):pass
    return None

def open_panel(no_browser=False):
    prepare_storage();info=existing_server()
    if not info:
        command=[sys.executable,str(pathlib.Path(__file__).resolve()),'serve']
        options={'cwd':str(ROOT),'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,
                 'env':dict(os.environ,FEISHU_TODO_HOME=str(ROOT),FEISHU_TODO_PROFILE=PROFILE)}
        if os.name=='nt':options['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS
        else:options['start_new_session']=True
        subprocess.Popen(command,**options)
        for _ in range(50):
            time.sleep(0.1);info=existing_server()
            if info:break
        if not info:raise RuntimeError('无法启动本机控制台，请检查Python运行环境。')
    url=info['url']+'/#'+info['token']
    if not no_browser:webbrowser.open(url)
    print('已打开本机待办助手控制台。关闭网页不会关闭助手；请使用页面里的开关。')
    return url

def install_entry(desktop=None):
    deployed=service.deploy();target=pathlib.Path(desktop) if desktop else pathlib.Path.home()/'Desktop'
    if desktop is None and os.name=='nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                target=pathlib.Path(os.path.expandvars(winreg.QueryValueEx(key,'Desktop')[0]))
        except OSError:pass
    target.mkdir(parents=True,exist_ok=True);script=str(deployed/'scripts/control_panel.py')
    if os.name=='nt':
        entry=target/'飞书待办控制台.cmd'
        lines=['@echo off','set '+service.windows_quote('FEISHU_TODO_HOME='+str(ROOT)),
               'set '+service.windows_quote('FEISHU_TODO_PROFILE='+PROFILE),
               service.windows_quote(sys.executable)+' '+service.windows_quote(script)+' open','if errorlevel 1 pause']
        entry.write_text('\r\n'.join(lines)+'\r\n')
    else:
        entry=target/('飞书待办控制台.command' if sys.platform=='darwin' else '飞书待办控制台.sh')
        entry.write_text('#!/bin/sh\nexport FEISHU_TODO_HOME='+shlex.quote(str(ROOT))+'\nexport FEISHU_TODO_PROFILE='+shlex.quote(PROFILE)+
                         '\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(script)+' open\n');entry.chmod(0o700)
    return {'entry_created':True,'entry':str(entry),'business_state_changed':False}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['open','serve','install-entry','status']);args=parser.parse_args()
    if args.command=='serve':serve()
    elif args.command=='open':open_panel()
    elif args.command=='install-entry':print(json.dumps(install_entry(),ensure_ascii=False))
    else:print(json.dumps(get_status(),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
