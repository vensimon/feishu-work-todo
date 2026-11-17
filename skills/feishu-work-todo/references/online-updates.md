# GitHub在线规则与样式

本技能1.1.0及以后可自动读取维护者在GitHub提交的 `live/config.json`。不下载或执行远程Python、shell或SKILL.md。代码功能变化仍使用新版安装包，规则和样式变化无需反复安装。

## 订阅

分发包的 `assets/online-source.json` 可预先包含通用仓库地址（不是账号凭证）；运行时先看个人目录内的同名文件，没有则用包内默认。每次 `collect.py` 和实际发送前都会检查更新。提取前还必须运行并阅读：

```sh
python3 scripts/online_config.py sync
```

它输出有效配置路径、提取规则路径和本次同步状态。AI必须完整读取 `rules_file` 再分析，不能继续照抄旧的固定提取规则。日期窗参数由收集脚本直接应用，卡片style由渲染脚本直接应用。

更换源时需使用者明确选择其信任的仓库，再运行：

```sh
python3 scripts/online_config.py bind --repo OWNER/REPOSITORY --ref main --path live/config.json
python3 scripts/online_config.py status
```

绑定会先联网读取并验证文件；失败时保留旧订阅，不写入一个不可用的新源。公开仓库使用固定的GitHub Raw文件地址，无需GitHub登录；私有仓库需使用者自己的读取权限，并在AI宿主/定时任务环境提供 `FEISHU_TODO_GITHUB_TOKEN`，改用GitHub Contents API读取。不要把token写进包、URL、JSON或发给分享者，不使用会过期的私有下载URL。

## 何时生效

修改提交到绑定分支后，下一次整理读取新规则、下一次生成消息采用新样式；不主动覆盖已经发送的旧卡片，也不重复发送当天清单。可立即运行sync并渲染预览进行检查，但不要为了预览另外发一条工作清单。

扫描天数只影响尚未建立初始水位的安装。修改已有安装的首次扫描天数不自动清空水位或全量重扫。未完成台账没有15天到期删除规则。

显示文案、颜色不改变原有按钮名/提交字段或任务映射。表格结构、统计公式、定时唤起时间与宿主权限不是这个配置的更新范围；变更这些能力需升级程序或在本人宿主重新核验调度。

## 个人偏好与回退

个人目录中的 `local-preferences.json` 可只填写需要覆盖的字段。例如：

```json
{"style":{"header_template":"purple"},"collection":{"first_scan_days":7}}
```

优先级为：个人偏好 > 最近可用远程配置 > 包内默认。公共更新不写个人偏好、不改state、身份、表格、任务完成状态或收件人。

网络失败、无读取权限、JSON错误、不支持的字段或需要更高客户端版本时，保留最近有效缓存；没有缓存才用包内默认。同步返回warning与具体模式，不能将回退说成已经获取新版。支持：

```sh
python3 scripts/online_config.py pause
python3 scripts/online_config.py rollback
python3 scripts/online_config.py resume
```

pause暂停本机订阅但保留缓存；rollback退回同一订阅源上一版有效缓存并暂停；resume重新尝试最新版本。以上不更改其他使用者。

## 从1.0升级一次

1.0没有此功能，须用1.1安装包替换本地技能一次。不要复制别人运行目录，不重建个人表格，不重置state。若本人已经启用接收进程，还需同步更新本人应用数据目录中的程序副本（`service.py install --confirm`）；这只更新同一安装的代码。核验本人身份、doctor、配置同步与零业务影响的按钮验证。宿主已有定时任务的正文应改成“运行技能并读取本次有效在线规则”，然后读回核验；不能把更新正文当成新建了一份定时任务。
