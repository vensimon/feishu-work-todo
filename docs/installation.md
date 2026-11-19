# 安装与升级

当前是待跨宿主验收的试用包；下面的路径依据官方能力说明，不能代替目标客户端的实际导入与全流程验证。开始前先看[兼容性状态](compatibility.md)。

## 新用户

1. [点击下载 v1.6.0 技能安装包](https://github.com/vensimon/feishu-work-todo/releases/download/v1.6.0/feishu-work-todo-1.6.0.zip)，文件名为 `feishu-work-todo-1.6.0.zip`。如从[发布页](https://github.com/vensimon/feishu-work-todo/releases/latest)进入，选择Assets下的这个ZIP，不要下载Source code。
2. 豆包工作：在技能入口导入本地技能文件，或把包交给AI请求引导安装。Kiro：解压后在 Agent Steering & Skills → + → Import a skill → Local folder 中选择 `feishu-work-todo`。
3. 把README中的初始化话术发给AI，由其按技能引导完成依赖、本人授权、独立应用、台账、卡片回调和定时核验。
4. 默认GitHub源随包提供。初次运行 `online_config.py sync` 检查规则版本；公开源无需GitHub授权，私有源需要本人读取权限。
5. 初始化后由AI在本人允许后启动接收端，并验证卡片和定时。日后说“暂停待办助手”或“恢复待办助手”，由AI操作，不安装独立网页或桌面入口。详见[对话启停](../skills/feishu-work-todo/references/pause-resume.md)。

## 升级到1.5

替换技能目录并保留个人运行目录、飞书授权和台账，无需重新建应用或表。新生成清单会在每条待办下方显示“查看原消息 ↗”。更新旧卡片时须保留全部控件名称、映射和完成状态；直接使用原卡片补入口，不重发、不重排。单纯同步GitHub文字配置不会安装新增渲染代码，需要升级一次技能包。

1.5.1的按钮联动试验已撤回。后续版本恢复form＋checker的多选后统一提交；替换技能并更新本人的运行副本，保留个人完成状态和来源链接，不重新启用勾选联动。

## 1.6新增会议与通知来源

升级技能并保留原台账。按[来源说明](../skills/feishu-work-todo/references/work-sources.md)核验本人的相关通知机器人，自定义会话ID只登记在自己的state.source_settings，不复制分享者ID。新增来源首次回看15天，再按各来源水位增量；不要重建个人表格或重开旧完成项。

读取会议与文档所需的权限按当前CLI错误或schema逐项核验，仅请求本功能实际需要的用户读取权限。会议检索无权不代表没有会议；通知、妙记及原有聊天中已授权的部分继续处理，失败来源在清单中保留待确认。导入成功不代表全部企业资源已可读取，不能承诺免审核。

每日任务正文必须读取source-evidence.json，并与审核候选一起逐项记录筛选结果。只复制旧的“排除所有机器人私聊”任务正文会漏掉通知；以当前技能来源说明为准。按钮交互沿用原来的表单批量确认。

## 1.4的启停方式变更

替换技能包，保留自己的运行目录、授权与台账。新版不再生成独立控制台或桌面入口，旧快捷方式可自行删除。原定时任务若写死control_panel.py status，由AI更新为service.py status；仅引用当前技能的任务按新规则执行。替换安装包不会自动暂停、恢复、重建表格或重复创建任务。

GitHub安装源代码可直接定位 `skills/feishu-work-todo`，不要把整个仓库当作技能目录，也不要把当前使用者的运行目录发给别人。

Codex本地客户端：按官方本地技能机制，将解压的 `feishu-work-todo` 文件夹放入使用者自己的 `~/.agents/skills/`，或项目的 `.agents/skills/`；也可让其内置技能安装器按仓库及技能子目录安装。先确认技能已被识别，再初始化。Codex云端、Web会话与本地桌面运行环境不同，不自动视为适配。

## 已安装1.0

只需升级一次到1.1：替换技能程序，保留当前使用者的应用数据目录、CLI profile、台账和全部状态。不要重新初始化一套Base，不复制分享者的配置。

已有登录启动接收进程时，也需更新其应用数据目录内的程序副本，并核验接收端和原有定时任务正文。完整步骤见[技能在线更新说明](../skills/feishu-work-todo/references/online-updates.md)。升级后，后续规则和样式修改通过GitHub同步。

## 运行条件

每人使用自己的账号、表格、应用和电脑环境。默认本地部署需要自己的电脑开机联网，回调接收进程保持可用；与分享者电脑无关。首次本人授权和企业权限策略仍适用，不能承诺免审核。

定时与卡片保存必须分别验证。Kiro导入技能本身不产生时钟任务；宿主缺少能力时应报告具体缺项，不假称已启用。

豆包工作官方描述定时任务在云端运行；本包的本地CLI profile、用户状态文件和登录启动接收端能否在该定时环境中使用，仍是未验证的适配项。不能仅创建一个云端定时任务就报告本地方案已经全程可用。

## 官方参考

- [Kiro Agent Skills](https://kiro.dev/docs/skills/)
- [豆包工作技能与定时任务介绍](https://www.feishu.cn/content/article/7677519271848610746)
- [Kiro CLI Headless](https://kiro.dev/docs/cli/headless/)
- [飞书CLI](https://github.com/larksuite/cli)
- [Codex技能](https://developers.openai.com/codex/skills)
- [Codex定时任务](https://developers.openai.com/codex/app/automations)
