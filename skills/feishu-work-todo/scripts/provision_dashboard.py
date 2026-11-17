"""Build a native, reactive dashboard without replacing the user's task data."""
import datetime as dt
import json
import uuid
from dashboard_support import ROOT,TABLE,TZ,call,rows,save,create_records,ensure_calendar

def main():
    state=json.loads((ROOT/'state.json').read_text())
    source_fields=call('+field-list',table=TABLE)['fields']
    fields={f['name']:f for f in source_fields}
    new=[{'name':'确认完成时间','type':'datetime','style':{'format':'yyyy-MM-dd HH:mm'},'description':'勾选处理完毕的确认时间，不代表实际工作完成时间；自动从变更历史与后续勾选记录维护。'}]
    missing=[f for f in new if f['name'] not in fields]
    if missing:save('dashboard-source-fields-created.json',call('+field-create',table=TABLE,body=missing))
    formulas=[
      {'name':'未处理天数','type':'formula','expression':'IF([处理完毕],0,IF(ISBLANK([来源日期]),0,MAX(0,INT(DAYS(TODAY(),[来源日期])))))'},
      {'name':'滞留分层','type':'formula','expression':'IF([处理完毕],"已完成",IF(ISBLANK([来源日期]),"来源日期未填",IF([未处理天数]>=14,"14天及以上",IF([未处理天数]>=7,"7–13天",IF([未处理天数]>=3,"3–6天","0–2天")))))'},
      {'name':'仪表盘事项名称','type':'formula','expression':'"【"&IFBLANK([本人职责],"职责待确认")&"】"&[事项]'},
    ]
    missing=[f for f in formulas if f['name'] not in fields]
    if missing:save('dashboard-source-formulas-created.json',call('+field-create','--i-have-read-guide',table=TABLE,body=missing))
    tables={t['name']:t for t in call('+table-list')['tables']}
    if '处理流水' not in tables:
        schema=[{'name':n,'type':t} for n,t in [('流水编号','text'),('事项编号','text'),('事项','text'),('动作','text'),('发生时间','datetime'),('待办变化','number')]]
        save('dashboard-ledger-create.json',call('+table-create','--name','处理流水','--fields',json.dumps(schema,ensure_ascii=False)))
        tables={t['name']:t for t in call('+table-list')['tables']}
    ledger_id=tables['处理流水']['id']
    ledger_fields={f['name']:f for f in call('+field-list',table=ledger_id)['fields']}
    if '计入统计' not in ledger_fields:
        call('+field-create','--i-have-read-guide',table=ledger_id,body={'name':'计入统计','type':'formula','expression':'IF(LEFT([事项编号],2)="__",0,1)'})
    events=[];updates={}
    if '周期统计' not in tables:
        schema=[{'name':'周期编号','type':'text'},
                {'name':'周期类型','type':'select','multiple':False,'options':[{'name':'日'},{'name':'周'}]},
                {'name':'周期开始','type':'datetime','style':{'format':'yyyy-MM-dd'}},
                {'name':'周期结束','type':'datetime','style':{'format':'yyyy-MM-dd'}},
                {'name':'周期标签','type':'text'}]
        save('dashboard-period-create.json',call('+table-create','--name','周期统计','--fields',json.dumps(schema,ensure_ascii=False)))
        tables={t['name']:t for t in call('+table-list')['tables']}
    period_id=tables['周期统计']['id']
    # Verify all cross-table schema names before defining calculated columns.
    for table in [TABLE,ledger_id,period_id]:call('+table-get',table=table)
    formulas=[
      {'name':'新增事项','type':'formula','expression':'[待办清单].COUNTIF(LEFT(CurrentValue.[事项编号],2)!="__" && CurrentValue.[来源日期]>=[周期开始] && CurrentValue.[来源日期]<[周期结束])'},
      {'name':'确认完成','type':'formula','expression':'[处理流水].COUNTIF(CurrentValue.[计入统计]=1 && CurrentValue.[动作]="确认完成" && CurrentValue.[发生时间]>=[周期开始] && CurrentValue.[发生时间]<[周期结束])'},
      {'name':'重新打开','type':'formula','expression':'[处理流水].COUNTIF(CurrentValue.[计入统计]=1 && CurrentValue.[动作]="重新打开" && CurrentValue.[发生时间]>=[周期开始] && CurrentValue.[发生时间]<[周期结束])'},
      {'name':'期末待处理','type':'formula','expression':'MAX(0,[待办清单].COUNTIF(LEFT(CurrentValue.[事项编号],2)!="__" && NOT(ISBLANK(CurrentValue.[来源日期])) && CurrentValue.[来源日期]<[周期结束])+IFBLANK([处理流水].FILTER(CurrentValue.[计入统计]=1 && CurrentValue.[发生时间]<[周期结束]).[待办变化].SUM(),0))'},
      {'name':'已到周期','type':'formula','expression':'IF([周期开始]<=TODAY(),1,0)'},
      {'name':'当前周期','type':'formula','expression':'IF([周期开始]<=TODAY() && [周期结束]>TODAY(),1,0)'},
    ]
    pf={f['name']:f for f in call('+field-list',table=period_id)['fields']}
    missing=[f for f in formulas if f['name'] not in pf]
    if missing:save('dashboard-period-formulas-created.json',call('+field-create','--i-have-read-guide',table=period_id,body=missing))
    state['dashboard']={**state.get('dashboard',{}),'ledger_table_id':ledger_id,'period_table_id':period_id,'long_pending_threshold_days':7,'very_long_threshold_days':14,'week_start':'Monday','completion_metric':'confirmation events, reopen separately','historical_backlog':'reconstructed from current registered task source dates and completion/reopen events'}
    save('state.json',state)
    calendar=ensure_calendar(state)
    source_fields=call('+field-list',table=TABLE)['fields'];fields={f['name']:f for f in source_fields}
    state['base']['fields'].update({n:f['id'] for n,f in fields.items()})
    # Native workflows record only state transitions; they send no messages.
    workflows={w['title']:w for w in call('+workflow-list')['items']}
    ids={}
    for done,title in [(True,'待办统计 · 记录确认完成'),(False,'待办统计 · 记录重新打开')]:
        if title in workflows:wid=workflows[title]['workflow_id']
        else:
            val=lambda t,v:{'value_type':t,'value':v}
            ref=lambda path:[val('ref','$.record_change.'+path)]
            log_fields=[{'field_name':'流水编号','value':[val('text','live:'),*ref('recordId'),val('text',':'),*ref('startTime'),val('text',':done' if done else ':reopen')]},
                        {'field_name':'事项编号','value':ref(fields['事项编号']['id'])},
                        {'field_name':'事项','value':ref(fields['事项']['id'])},
                        {'field_name':'动作','value':[val('text','确认完成' if done else '重新打开')]},
                        {'field_name':'发生时间','value':ref('recordModifiedTime')},
                        {'field_name':'待办变化','value':[val('number',-1 if done else 1)]}]
            trigger={'id':'record_change','type':'SetRecordTrigger','title':'处理完毕状态变化','next':'save_time' if done else 'save_event',
                     'data':{'table_name':'待办清单','record_watch_conjunction':'and',
                             'record_watch_info':[{'field_name':'处理完毕','operator':'is','value':[val('boolean',not done)]}],
                             'field_watch_info':[{'field_name':'处理完毕','operator':'is','value':[val('boolean',done)]}],
                             'trigger_control_list':['pasteUpdate','automationBatchUpdate','syncUpdate','appendImport']}}
            steps=[trigger]
            if done:steps.append({'id':'save_time','type':'SetRecordAction','title':'保存确认完成时间','next':'save_event','data':{
                'table_name':'待办清单','ref_info':{'step_id':'record_change'},'field_values':[{'field_name':'确认完成时间','value':ref('recordModifiedTime')}]}})
            steps.append({'id':'save_event','type':'AddRecordAction','title':'保存状态变更流水','next':None,'data':{'table_name':'处理流水','field_values':log_fields}})
            body={'client_token':str(uuid.uuid4()),'title':title,'steps':steps}
            save('dashboard-workflow-plan-'+str(done)+'.json',body)
            result=call('+workflow-create',body=body);wid=result['workflow_id']
            save('dashboard-workflow-create-'+str(done)+'.json',result)
        call('+workflow-enable','--workflow-id',wid)
        ids['complete' if done else 'reopen']=wid
    state['dashboard']['workflow_ids']=ids
    views=call('+view-list',table=TABLE)['views'];by_name={v['name']:v for v in views}
    name='长期未处理（7天+）'
    if name not in by_name:
        call('+view-create',table=TABLE,body={'name':name,'type':'grid'})
        by_name={v['name']:v for v in call('+view-list',table=TABLE)['views']}
    vid=by_name[name]['id']
    call('+view-set-filter','--view-id',vid,table=TABLE,body={'logic':'and','conditions':[['处理完毕','==',False],['未处理天数','>=',7],['事项编号','!=','__chat_button_test__']]})
    call('+view-set-sort','--view-id',vid,table=TABLE,body={'sort_config':[{'field':'未处理天数','desc':True},{'field':'截止日期','desc':False}]})
    call('+view-set-group','--view-id',vid,table=TABLE,body={'group_config':[{'field':'滞留分层','desc':True},{'field':'跟进类型','desc':False}]})
    call('+view-set-visible-fields','--view-id',vid,table=TABLE,body={'visible_fields':['事项','处理完毕','跟进类型','事项分类','未处理天数','滞留分层','来源日期','截止日期','下一步','原消息']})
    state['dashboard']['long_pending_view_id']=vid
    save('state.json',state)
    print(json.dumps({'ok':True,'backfilled_events':len(events),'completion_times_backfilled':len(updates),'calendar_rows_added':calendar,'dashboard_support':state['dashboard']},ensure_ascii=False))

if __name__=='__main__':main()
