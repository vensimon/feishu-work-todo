# 待办提案协议

由AI阅读当前安装收集到的真实消息后生成JSON数组。不能把下面的示例当成真实工作写入；ID、链接和来源必须来自本次CLI证据。

```json
[
  {
    "key": "稳定项目标识-当前动作",
    "title": "简短事项名称",
    "role": "由你复核",
    "followup": "待他人反馈",
    "category": "交付与评审",
    "summary": "等协作方明确完成交付后，复核结果。",
    "next_step": "说明协作方实际执行内容、本人的复核内容及触发条件。",
    "execution_owner": "从证据识别的执行人",
    "date_note": "具体截止日期未明确",
    "deadline": null,
    "source": {
      "message_id": "CLI返回的om消息ID",
      "chat_id": "CLI返回的oc会话ID",
      "time": "消息的北京时间，如YYYY-MM-DD HH:mm",
      "sender": "消息发送人",
      "url": "CLI返回的message_app_link"
    }
  }
]
```

`role`为实际本人职责，默认库含执行/确认/复核/职责待确认，可在真实需要时追加。`followup`为进展，初始为待处理/待他人反馈/需确认。`category`初始为项目推进/交付与评审/团队管理/流程与数据/其他，可独立扩展。

不接受 `completed` 属性：提取聊天不能替本人宣告完成。已有完成记录不会由 upsert 重开；记录不存在但本地保留旧record_id时视为被删除，不依据旧聊天复活。写入只影响当前个人安装登记的表。

会议、文档和多维表格记录没有消息ID时，source使用真实原生来源，不伪造消息或会话。例如：

```json
{"kind":"minutes","id":"CLI返回的minute_token","url":"CLI返回的原妙记链接","time":"2026-01-05T09:00:00+08:00"}
```

kind可为minutes、note、docx、base_record，id为相应真实标识，url必须为已核验的HTTPS来源；time来自实际会议、文档请求或记录事件，不用本次扫描时间替代。消息来源仍默认kind=message，保留真实message_id与chat_id。一个事项出现于多个来源时合并key，原来源保留，supporting_sources可追加补充依据。

完整解析输出供AI检查，简短摘要供卡片展示。提案本身是本人的运行数据，保存在应用数据目录，不回写到可转发的技能包。
