# 在线维护规则与样式

## 你日常只需要改一个文件

打开仓库里的 [live/config.json](../live/config.json)，点击编辑，修改后提交到main分支。也可以把仓库链接交给有写权限的AI，告诉它“修改提取规则／清单样式，并验证配置”。

各使用者下一次整理/生成清单会读取新版；不会立即给所有人重新发消息，也不重排已发送卡片。GitHub Raw可能有短暂缓存，以客户端同步返回的版本和文件摘要为准；可运行 `online_config.py sync` 立即检查，不承诺提交后瞬时全员生效。

## 常改字段

| 字段 | 用途 | 例子 |
| --- | --- | --- |
| version | 本次规则版本，便于查问题 | 2026-11-18.1 |
| collection.first_scan_days | 首次扫描天数，1–90 | 15 |
| collection.overlap_hours | 增量回溯小时，0–168 | 48 |
| collection.exclude_groups_containing | 明显休闲群名称关键词 | 表情包、摸鱼 |
| extraction.guidance | 给AI的待办提取指导，一条一个字符串 | 明确执行人与本人的复核职责 |
| extraction.summary_max_chars | 摘要字数上限，10–90 | 60 |
| style.title_template | 卡片标题，允许{date} | 工作待办清单 · {date} |
| style.subtitle_template | 副标题，允许{count} | {count}项待办 · 勾选后统一保存 |
| style.header_template | 卡片主题色 | blue、purple、green |
| style.role_colors | 每个职责标签的颜色 | 由你复核：purple |
| style.role_order | 职责排序 | 执行、确认、复核 |
| style.deadline_label / next_step_label | 两行详情的提示词 | 截止、下一步 |
| style.show_deadline / show_next_step | 是否显示相应详情行 | true / false |
| style.detail_bullet | 详情项目符号 | •、·、- |
| style.title_bold | 事项名称是否加粗 | true |

其他style字段直接对应介绍、空清单说明、按钮文字和无日期提示。保持所有字段，不改JSON键名、格式版本或min_client，除非确实更改了客户端协议。新增职责配色不等于自动增加Base选项；AI按真实证据提取新职责时，会沿用技能的只追加选项流程。

规则指导可以描述筛选、归属、分组和表达方式，不能索取密钥、扩大聊天授权、修改收件人或自动标完成。完成和个人编辑保护是客户端边界，不由公共配置关闭。

## 同步、校验和回退

客户端每次收集、发送前检查更新；AI提取前还须读取输出的active-rules.md。程序验证字段类型、颜色、模板占位符、扫描范围和最低客户端版本。配置有误时不会覆盖上次有效版本。CI也会检查live配置，但直接提交main时客户端可能先看到新文件，因此不要依赖CI替代客户端校验。

公共更新不会覆盖个人local-preferences.json。出错可在GitHub还原提交；个人也可pause或rollback（回退后暂停），修复后resume。

## 哪些修改仍需程序升级

新增接口、修改表结构/统计公式、更改完成交互、权限或调度实现，属于程序升级；不能伪装成远程配置执行。每天实际唤起时间由各自宿主的已核验任务控制。修改配置里的文案不会自动更改操作系统定时任务。

## GitHub可见范围

公开源使用Raw HTTPS读取，无需同事GitHub登录。私有源需每位同事有仓库读取权限，并由自己的宿主提供读取token，使用Contents API。不要把维护者token发给同事。官方接口说明：[Repository contents](https://docs.github.com/en/rest/repos/contents)。

## 1.3审核筛选更新

2026-11-18.1的文字规则可由旧版在线同步，新增审核候选核对脚本和发送检查需要升级1.3.0安装包。升级后每日任务仍引用同一个feishu-work-todo技能；按daily.md为finish-scan追加证据目录与review-ledger参数，不重建个人台账或重新授权。仅同步guidance不等于获得新代码。
