# 安装、个人初始化与就绪核验

## 如何交给同事

把完整 ZIP 发给同事。同事可在豆包工作中导入本地技能，或把包交给它并说“安装此技能并初始化我的飞书工作待办”。Kiro 选择 Agent Steering & Skills → + → Import a skill → Local folder，导入解压后的 `feishu-work-todo` 文件夹；也可以让 Kiro 帮忙导入该本地文件夹。

不要求登录分享者账号，不修改分享者系统。第一次需要使用者自己完成飞书授权；界面按钮名称以使用者客户端版本为准。

## 依赖和身份

需要 Python 3.9+、可用的飞书 CLI，以及能执行本地脚本的 AI 宿主。脚本路径相对本技能目录；Python 命令按系统选择 `python3`、`python` 或 `py -3`。安装 CLI 时先核验官方安装说明，不从第三方脚本索取或收集凭证。

脚本默认使用独立 CLI profile `feishu-work-todo`。先运行：

```sh
python3 scripts/manage.py doctor
lark-cli --profile feishu-work-todo auth status
```

若该 profile 尚不存在，使用 CLI 的自助流程为当前使用者创建独立应用：

```sh
lark-cli config init --new --name feishu-work-todo
```

命令会等待本人完成浏览器操作，使用宿主的异步进程方式运行；原样展示 verification URL 并按 `lark-cli auth qrcode --help` 生成二维码。不要替别人完成授权，不读取或复制另一个 profile 的密钥。

如使用者已经有自己的专用应用，可以选择自己的 profile，并在本次环境设置 `FEISHU_TODO_PROFILE`；这不是分享者 profile 的副本。初始化会同时绑定当前 user open_id 和 app_id，之后不匹配时停止写入。

在 CLI 可用后，读取它随附的 `lark-shared`、`lark-im`、`lark-base` 指南；创建公式前读取其 formula guide。可通过 `lark-cli skills read <技能或参考标识>` 获取。初版适配于有 Base v3 shortcuts 和 Card 2.0 的 CLI；先用 `--help` 验证当前命令能力。

1.1.0起先运行 `python3 scripts/online_config.py sync` 并读取输出的提取规则；在线源与升级说明见 [online-updates.md](online-updates.md)。绑定的仓库只提供通用配置，个人授权、数据和接收进程仍完全独立。

## 授权范围

需要本人聊天读取/检索、给本人发消息与更新自有卡片，以及本人多维表格的表、字段、记录、视图、工作流和仪表盘读写。使用 `auth login --scope` 请求本功能实际所需的 scope，不用 `--domain all`，不申请无关原生任务、邮箱或组织管理权限。具体 scope 从当前 CLI schema/官方接口说明核验。

用 `lark-cli --profile feishu-work-todo auth login --no-wait --json ...` 时按返回链接让本人授权，再根据 device code 完成；不得把 device code 或 token 放进分发包。企业是否允许相关权限由其策略决定，不能承诺免审核。

本人确认创建后运行：

```sh
python3 scripts/manage.py init --confirm
```

只新建空白个人资源。若初始化中断，保留已返回的资源ID并复用；创建响应不确定时先核验，不删除资源、不无条件重新建一整套。

## 可勾选卡片

当前应用须启用机器人能力、对本人可用，并在开放平台“事件与回调”中仅配置本功能所需的 `card.action.trigger`，发布使其生效。先检查已有配置；本技能没有一个能跳过企业应用政策的“免授权”按钮。

不要把同一个应用的独立长连接接收器复制给许多同事：长连接是集群推送，不是广播。每位同事使用自己的应用/接收端，或另行建设有按用户路由的统一服务；本包不把个人接收器冒充多人服务器。

有界探测：

```sh
lark-cli --profile feishu-work-todo event consume card.action.trigger --as bot --timeout 10s
```

应看到 ready marker 和连接成功，再由使用者决定是否允许本人的登录启动接收进程。明确允许后运行：

```sh
python3 scripts/service.py resume --confirm
python3 scripts/manage.py doctor
```

初始化后保持暂停，由AI在本人允许后启动接收端。macOS使用本人LaunchAgent，代码复制到本人应用数据目录避免“文稿”目录的后台访问限制。Windows提供用户级登录任务，需在目标机器验证策略和路径；Linux启动本次用户会话的接收进程，不自动安装登录服务。日后通过AI对话暂停或恢复，见[pause-resume.md](pause-resume.md)，保留表格与历史，不安装独立控制台。

运行 `python3 scripts/verify_callback.py send` 给本人发送专用验证卡片。请本人点击“验证提交”，再运行 `python3 scripts/verify_callback.py check`，必须同时核对提交保存与原卡片更新成功。这个探针不创建工作记录，也不修改完成状态，空白新安装也能验证。正式清单发送脚本在此项通过前会拒绝发送。未验证接收功能时，可发送明确标注只读的文字摘要，不能发送假可交互按钮。

## 定时能力：技能不等于调度器

豆包工作：使用其实际提供的定时任务工具，创建当前使用者的工作日整理任务，并读回任务ID、时间和启用状态。

Kiro：IDE技能导入本身不创建时钟任务。若使用本地 CLI 定时运行，当前官方 headless 文档要求使用者自己的 `KIRO_API_KEY`；仍须配置并验证本人操作系统调度、受限工具策略和 CLI 环境。不要把 IDE Hooks 或仅针对云端代码仓库的 Web Schedule 当成本机飞书任务调度，也不要默认开启 `--trust-all-tools`。若使用者没有这项能力，清楚报告“手动运行可用，自动每日扫描尚未配置”，不假称每天会执行。

通用任务正文见 daily.md。目标是09:40准备、10:00发一张卡片。用宿主真实的创建/更新工具，不输出伪定时指令；重复安装先找已存在的任务。只有在任务真实创建并核验后，才能使用 `manage.py schedule-record --host <宿主名> --job-id <真实ID>` 记录它。

就绪报告分别列出：本人授权、空白台账、首次扫描、卡片提交、接收进程、每日调度。导入ZIP成功不代表后五项已经完成。

## 官方参考

- Kiro Agent Skills：https://kiro.dev/docs/skills/
- Kiro Headless：https://kiro.dev/docs/cli/headless/
- 飞书CLI：https://github.com/larksuite/cli
- 飞书长连接：https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-
- 豆包工作技能入口：https://www.feishu.cn/content/article/7677519271848610746
