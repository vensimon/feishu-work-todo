"""Check portable sources without touching an actual installation or network."""
import ast
import json
import os
import pathlib
import re
import sys
import tempfile

REPO=pathlib.Path(__file__).resolve().parents[1]
SKILL=REPO/'skills/feishu-work-todo'

def main():
    forbidden=[r'(?:ou_|oc_|om_|cli_)[0-9a-f]{20,}',r'gh[pousr]_[A-Za-z0-9]{24,}','/'+'Users/[^/\\s]+/']
    files=[]
    for folder in ['skills','live','docs','tests','tools']:
        files.extend(p for p in (REPO/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ['.py','.md','.json','.html','.cmd','.command','.sh'])
    for path in files:
        content=path.read_text()
        if path.suffix=='.py':ast.parse(content,filename=str(path))
        if path.suffix=='.json':json.loads(content)
        for pattern in forbidden:
            if re.search(pattern,content):raise ValueError('Possible personal data/credential in '+str(path.relative_to(REPO)))
    text=(SKILL/'SKILL.md').read_text()
    if not re.match(r'^---\nname: feishu-work-todo\ndescription: [^\n]+\n---\n',text):raise ValueError('Invalid skill frontmatter')
    with tempfile.TemporaryDirectory(prefix='todo-validate-') as runtime:
        os.environ['FEISHU_TODO_HOME']=runtime
        sys.path.insert(0,str(SKILL/'scripts'))
        import online_config
        online_config.validate(json.loads((REPO/'live/config.json').read_text()))
        online_config.validate(json.loads((SKILL/'assets/default-config.json').read_text()))
        source=json.loads((SKILL/'assets/online-source.json').read_text())
        if source.get('repository'):online_config.validate_source(source)
    print(json.dumps({'ok':True,'checked_files':len(files),'network_calls':0,'personal_installation_touched':False}))

if __name__=='__main__':main()
