"""One Card 2.0 form: check completed items, then submit once."""
import argparse
import datetime
import json
import pathlib

from runtime_paths import ROOT
from online_config import get_config
FOLLOWUP_ORDER={'待处理':0,'需确认':1,'待他人反馈':2}
ROLE_ORDER={'由你执行':0,'由你确认':1,'由你复核':2}
ROLE_COLORS={'由你执行':'blue','由你确认':'orange','由你复核':'purple'}

def responsibility(item):
    values=item.get('base_user_role') or []
    if isinstance(values,str):values=[values]
    return values[0] if values else '职责待确认'

def role_color(role,style=None):
    colors=(style or get_config()['style'])['role_colors']
    if role in colors:return colors[role]
    if any(word in role for word in ['复核','评审','验收','校对']):return 'purple'
    if any(word in role for word in ['确认','审批','决策']):return 'orange'
    if any(word in role for word in ['执行','协调','跟进','推进','协助']):return 'blue'
    return 'neutral'

def followup(item):
    values=item.get('base_followup_type') or []
    if isinstance(values,str):values=[values]
    return values[0] if values else '需确认'

def deadline_label(item,style=None):
    style=style or get_config()['style']
    raw=item.get('base_deadline_date') if 'base_deadline_date' in item else item.get('deadline_date')
    if raw:
        try:return datetime.date.fromisoformat(str(raw)[:10]).isoformat()
        except ValueError:return style['uncertain_date_text']
    return style['uncertain_date_text'] if '待确认' in (item.get('base_date_note') or '') else style['unset_date_text']

def item_label(item,style=None):
    style=style or get_config()['style']
    title=(item.get('display_title') or item['title']).strip()
    kind=responsibility(item)
    prefix='【'+kind+'】'
    if title.startswith(prefix):title=title[len(prefix):].lstrip()
    summary=item.get('base_notification_summary') or item.get('base_next_step') or style['fallback_next_step']
    summary=' '.join(summary.split())
    badge="<text_tag color='"+role_color(kind,style)+"'>"+kind+'</text_tag>'
    lines=[badge+' '+('**'+title+'**' if style['title_bold'] else title)]
    if style['show_deadline']:lines.append(style['detail_bullet']+' '+style['deadline_label']+'：'+deadline_label(item,style))
    if style['show_next_step']:lines.append(style['detail_bullet']+' '+style['next_step_label']+'：'+summary)
    return '\n'.join(lines)

def build(items, preview=False,config=None):
    config=config or get_config();style=config['style']
    role_order={role:i for i,role in enumerate(style['role_order'])}
    pending=[item for item in items if not item.get('completed') and not item.get('base_record_missing')
             and not item['key'].startswith('__')]
    pending.sort(key=lambda item:(role_order.get(responsibility(item),len(role_order)),
                                 item.get('base_deadline_date') or '9999-12-31',
                                 item.get('base_source_date') or item.get('source_time') or '',item['key']))
    elements=[]
    mapping={}
    for index,item in enumerate(pending,1):
        name='todo_'+str(index).zfill(3)
        mapping[name]={'key':item['key'],'record_id':item['base_record_id']}
        label=item_label(item,style)
        elements.append({'tag':'checker','name':name,'checked':False,
                         'text':{'tag':'lark_md','content':label},
                         'checked_style':{'show_strikethrough':True}})
    elements.append({'tag':'button','name':'submit_done','text':{'tag':'plain_text','content':style['submit_text']},
                     'type':'primary_filled','width':'fill','form_action_type':'submit',
                     'disabled':preview or not pending,
                     **({'disabled_tips':{'tag':'plain_text','content':'预览：尚待启用卡片回传配置'}} if preview else {})})
    intro=style['intro']
    if not pending:
        intro=style['empty_intro']
        elements[-1]['text']['content']=style['complete_text']
    if preview:intro='**交互预览，暂不能保存**\n'+intro+'\n启用卡片提交后即可使用。'
    day=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
    card={'schema':'2.0','config':{'update_multi':True,'width_mode':'default','enable_forward':False},
          'header':{'title':{'tag':'plain_text','content':style['title_template'].format(date=day)+(' · 预览' if preview else '')},
                    'subtitle':{'tag':'plain_text','content':style['subtitle_template'].format(count=len(pending))},
                    'template':style['header_template'],'icon':{'tag':'standard_icon','token':'todo_colorful'}},
          'body':{'direction':'vertical','padding':'12px 12px 20px 12px','vertical_spacing':'12px',
                  'elements':[{'tag':'markdown','content':intro,'text_size':'notation'},
                              {'tag':'form','name':'todo_form','direction':'vertical','vertical_spacing':'16px',
                               'elements':elements}]}}
    assert len(mapping)==len(pending)
    assert len({element['name'] for element in elements})==len(elements)
    assert sum(element.get('form_action_type')=='submit' for element in elements)==1
    # P0-P7: one list/form, one primary submit, two body blocks, one color family.
    return card,mapping

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    state=json.loads((ROOT/'state.json').read_text())
    card,mapping=build(state['items'],args.preview)
    suffix='preview' if args.preview else 'production'
    (ROOT/('batch-card-'+suffix+'.json')).write_text(json.dumps(card,ensure_ascii=False,indent=2))
    (ROOT/('batch-card-'+suffix+'-mapping.json')).write_text(json.dumps(mapping,ensure_ascii=False,indent=2))
    print(json.dumps({'items':len(mapping),'mode':suffix,'primary_action':'确定完成'},ensure_ascii=False))
