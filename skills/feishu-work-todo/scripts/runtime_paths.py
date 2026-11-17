"""Per-installation storage and CLI profile. Contains no shared account configuration."""
import json
import os
import pathlib
import shutil
import subprocess
import sys

def storage_home():
    override=os.environ.get('FEISHU_TODO_HOME')
    if override:return pathlib.Path(override).expanduser().resolve()
    if sys.platform=='darwin':return pathlib.Path.home()/'Library/Application Support/FeishuWorkTodo'
    if os.name=='nt':return pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()/'AppData/Local'))/'FeishuWorkTodo'
    return pathlib.Path(os.environ.get('XDG_DATA_HOME',pathlib.Path.home()/'.local/share'))/'feishu-work-todo'

ROOT=storage_home()
PROFILE=os.environ.get('FEISHU_TODO_PROFILE','feishu-work-todo')
_config=json.loads((ROOT/'state.json').read_text()) if (ROOT/'state.json').exists() else {}
if _config.get('cli_profile') and _config['cli_profile']!=PROFILE:
    raise RuntimeError('FEISHU_TODO_PROFILE must match the profile bound to this installation')
CLI=os.environ.get('FEISHU_TODO_CLI') or _config.get('cli_path') or shutil.which('lark-cli') or 'lark-cli'
if pathlib.Path(CLI).suffix.lower() in ['.bat','.cmd']:
    raise RuntimeError('Use a native lark-cli executable, not a Windows batch wrapper')
CLI_ARGS=[CLI,'--profile',PROFILE]
ENV=dict(os.environ,LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1',LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')

def cli_json(args,cwd=None):
    result=subprocess.run([*CLI_ARGS,*args],cwd=cwd,env=ENV,capture_output=True,text=True,timeout=120)
    try:data=json.loads(result.stdout or result.stderr)
    except ValueError:raise RuntimeError('lark-cli did not return structured JSON; check installation and version')
    if result.returncode or data.get('ok') is False:
        error=data.get('error',{})
        raise RuntimeError(str(error.get('message','CLI request failed; inspect the original command locally')))
    return data

def current_identity():
    raw=cli_json(['auth','status'])
    user=raw.get('identities',{}).get('user',{})
    if user.get('status')!='ready' or not user.get('available') or not user.get('openId'):
        raise RuntimeError('Authorize your own Feishu account in the dedicated CLI profile first')
    if not raw.get('appId'):raise RuntimeError('No application is configured in the dedicated profile')
    return {'recipient_open_id':user['openId'],'recipient_name':user.get('userName',''),'application_id':raw['appId']}

def assert_identity(state):
    actual=current_identity()
    if any(actual.get(key)!=state.get(key) for key in ['recipient_open_id','application_id']):
        raise RuntimeError('Current user/application differs from this installation. No write was performed.')

def prepare_storage():
    if ROOT in [pathlib.Path('/'),pathlib.Path.home()]:raise RuntimeError('Choose a dedicated runtime subdirectory')
    ROOT.mkdir(parents=True,exist_ok=True)
    try:ROOT.chmod(0o700)
    except OSError:pass
    for name in ['cards','artifacts']:(ROOT/name).mkdir(exist_ok=True)

def write_state(state):
    prepare_storage()
    temp=ROOT/('state.'+str(os.getpid())+'.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    try:temp.chmod(0o600)
    except OSError:pass
    temp.replace(ROOT/'state.json')
