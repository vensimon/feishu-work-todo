"""Create the user-facing native dashboard from verified live table fields."""
import json
from dashboard_support import call,save,ROOT

def main():
    created=json.loads((ROOT/'dashboard-created.json').read_text())
    did=created.get('dashboard_id') or created.get('dashboard',{}).get('dashboard_id')
    if not did:raise RuntimeError('Missing dashboard ID')
    s=json.loads((ROOT/'state.json').read_text())
    for table in ['待办清单','处理流水','周期统计']:
        resolved=next(t for t in call('+table-list')['tables'] if t['name']==table)
        save('dashboard-schema-'+table+'.json',call('+field-list',table=resolved['id']))
    cond=lambda f,op,v:{'field_name':f,'operator':op,'value':v}
    fil=lambda conditions:{'conjunction':'and','conditions':conditions}
    real=[cond('事项编号','doesNotContain','__')]
    pending=real+[cond('处理完毕','is',False)]
    def stat(table,field=None,conditions=None):
        data={'table_name':table,'number_format':{'formatName':'digital_without_separator','precision':0}}
        data.update({'series':[{'field_name':field,'rollup':'SUM'}]} if field else {'count_all':True})
        if conditions:data['filter']=fil(conditions)
        return data
    def period(kind,series):
        return {'table_name':'周期统计','series':[{'field_name':f,'rollup':'SUM'} for f in series],
                'group_by':[{'field_name':'周期标签','mode':'integrated','sort':{'type':'group','order':'asc'}}],
                'filter':fil([cond('周期类型','is',kind),cond('已到周期','is',1)])}
    plans=[
      ('看板说明','text',{'text':'# 工作待办 · 处理与积压\n**处理量**按确认完成事件统计；重新打开单独留痕。每周按周一至周日统计。当前日、当前周为截至现在的数据。'}),
      ('今日确认完成','statistics',stat('周期统计','确认完成',[cond('周期类型','is','日'),cond('当前周期','is',1)])),
      ('本周确认完成','statistics',stat('周期统计','确认完成',[cond('周期类型','is','周'),cond('当前周期','is',1)])),
      ('当前待处理','statistics',stat('待办清单',conditions=pending)),
      ('7天以上未处理','statistics',stat('待办清单',conditions=pending+[cond('未处理天数','isGreaterEqual',7)])),
      ('日期已过待确认','statistics',stat('待办清单',conditions=pending+[cond('时间分类','is','日期已过·需确认')])),
      ('每日新增与确认完成','column',period('日',['新增事项','确认完成'])),
      ('每日待处理数量趋势','line',period('日',['期末待处理'])),
      ('每周新增与确认完成','column',period('周',['新增事项','确认完成'])),
      ('每周期末待处理趋势','line',period('周',['期末待处理'])),
      ('待处理 · 跟进类型分布','ring',{'table_name':'待办清单','count_all':True,'filter':fil(pending),'group_by':[{'field_name':'跟进类型','mode':'integrated','sort':{'type':'value','order':'desc'}}]}),
      ('待处理 · 业务分类分布','bar',{'table_name':'待办清单','count_all':True,'filter':fil(pending),'group_by':[{'field_name':'事项分类','mode':'integrated','sort':{'type':'value','order':'desc'}}]}),
      ('长期未处理区','text',{'text':'## 长期未处理 · 优先关注\n未处理天数从来源日期起算；**7天及以上**纳入长期待办，**14天及以上**重点关注。下方列出所有未完成事项并按等待天数排序，即使暂无7天以上事项也可查看最早积压的工作。完整明细与下一步可在“长期未处理（7天+）”视图维护。'}),
      ('未完成事项 · 等待天数排行','bar',{'table_name':'待办清单','series':[{'field_name':'未处理天数','rollup':'MAX'}],'filter':fil(pending),'group_by':[{'field_name':'仪表盘事项名称','mode':'integrated','sort':{'type':'value','order':'desc'}}]}),
      ('统计口径','text',{'text':'### 统计口径\n- 历史趋势按当前台账的来源日期和真实确认完成/重新打开流水回算，不把消息日期当完成日期。\n- 完成一次计一次处理；重新打开后再完成，会形成新的处理事件。期末待处理包含重新打开的事项。\n- 当前日、当前周未结束，趋势值为截至现在。测试事项不计入任何统计。\n- 确认完成流水与图表由飞书原生工作流、公式维护；聊天卡片和表格勾选共用状态。'})
    ]
    existing=call('+dashboard-block-list','--dashboard-id',did,'--page-size','100')
    if existing.get('has_more'):raise RuntimeError('Unexpected block pagination')
    by_name={b['name']:b for b in existing.get('items',existing.get('blocks',[]))}
    blocks={}
    for name,typ,config in plans:
        if name in by_name:
            blocks[name]=by_name[name];continue
        result=call('+dashboard-block-create','--dashboard-id',did,'--name',name,'--type',typ,'--data-config',json.dumps(config,ensure_ascii=False))
        blocks[name]=result
        save('dashboard-blocks-created.json',blocks)
        print(json.dumps({'created':name},ensure_ascii=False),flush=True)
    call('+dashboard-arrange','--dashboard-id',did)
    s=json.loads((ROOT/'state.json').read_text())
    s['dashboard'].update({'dashboard_id':did,'name':'工作待办 · 处理与积压仪表盘','block_count':len(plans)})
    save('state.json',s)
    save('dashboard-final.json',call('+dashboard-get','--dashboard-id',did))
    print(json.dumps({'ok':True,'dashboard_id':did,'blocks':len(plans)},ensure_ascii=False))

if __name__=='__main__':main()
