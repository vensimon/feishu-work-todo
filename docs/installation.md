# 安装与升级

## 新用户

1. 从仓库Releases下载 `feishu-work-todo-1.1.0.zip`。
2. 豆包工作：在技能入口导入本地技能文件，或把包交给AI请求引导安装。Kiro：解压后在 Agent Steering & Skills → + → Import a skill → Local folder 中选择 `feishu-work-todo`。
3. 把README中的初始化话术发给AI，由其按技能引导完成依赖、本人授权、独立应用、台账、卡片回调和定时核验。
4. 默认GitHub源随包提供。初次运行 `online_config.py sync` 检查规则版本；公开源无需GitHub授权，私有源需要本人读取权限。

GitHub安装源代码可直接定位 `skills/feishu-work-todo`，不要把整个仓库当作技能目录，也不要把当前使用者的运行目录发给别人。

## 已安装1.0

只需升级一次到1.1：替换技能程序，保留当前使用者的应用数据目录、CLI profile、台账和全部状态。不要重新初始化一套Base，不复制分享者的配置。

已有登录启动接收进程时，也需更新其应用数据目录内的程序副本，并核验接收端和原有定时任务正文。完整步骤见[技能在线更新说明](../skills/feishu-work-todo/references/online-updates.md)。升级后，后续规则和样式修改通过GitHub同步。

## 运行条件

每人使用自己的账号、表格、应用和电脑环境。默认本地部署需要自己的电脑开机联网，回调接收进程保持可用；与分享者电脑无关。首次本人授权和企业权限策略仍适用，不能承诺免审核。

定时与卡片保存必须分别验证。Kiro导入技能本身不产生时钟任务；宿主缺少能力时应报告具体缺项，不假称已启用。

## 官方参考

- [Kiro Agent Skills](https://kiro.dev/docs/skills/)
- [豆包工作技能与定时任务介绍](https://www.feishu.cn/content/article/7677519271848610746)
- [Kiro CLI Headless](https://kiro.dev/docs/cli/headless/)
- [飞书CLI](https://github.com/larksuite/cli)
