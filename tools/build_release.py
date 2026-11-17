"""Build one importable skill ZIP; no runtime data or entire-repository archives."""
import argparse
import ast
import hashlib
import json
import pathlib
import zipfile

REPO=pathlib.Path(__file__).resolve().parents[1]
SKILL=REPO/'skills/feishu-work-todo'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=pathlib.Path,default=REPO/'dist');args=parser.parse_args()
    version=None
    for node in ast.parse((SKILL/'scripts/online_config.py').read_text()).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CLIENT_VERSION' for t in node.targets):version=ast.literal_eval(node.value)
    if not version:raise ValueError('Missing client version')
    args.output.mkdir(parents=True,exist_ok=True);out=args.output/('feishu-work-todo-'+version+'.zip')
    entries=[]
    for file in sorted(SKILL.rglob('*')):
        if not file.is_file() or '__pycache__' in file.parts or file.suffix not in ['.py','.md','.json']:continue
        relative=file.relative_to(SKILL)
        if file.is_symlink() or (relative.parts[0] not in ['assets','references','scripts'] and str(relative)!='SKILL.md'):raise ValueError('Unexpected package resource')
        content=(REPO/'live/config.json').read_bytes() if str(relative)=='assets/default-config.json' else file.read_bytes()
        entries.append(('feishu-work-todo/'+relative.as_posix(),content))
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,content in entries:
            entry=zipfile.ZipInfo(name,(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o644<<16
            archive.writestr(entry,content)
    with zipfile.ZipFile(out) as archive:
        if archive.testzip():raise ValueError('ZIP integrity failed')
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix('.sha256').write_text(digest+'  '+out.name+'\n')
    print(json.dumps({'package':str(out),'files':len(entries),'bytes':out.stat().st_size,'sha256':digest}))

if __name__=='__main__':main()
