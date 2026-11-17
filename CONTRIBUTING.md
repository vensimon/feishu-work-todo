# 维护与开发

日常规则和样式只改 `live/config.json`，详细字段见[在线配置说明](docs/online-configuration.md)。保留JSON格式，不在配置里放账号、收件人、凭证、待办或消息内容。

程序改动在 `skills/feishu-work-todo/scripts/`。涉及用户数据写入时维持：本人身份与应用一致、只写自己的登记表、提取不能标完成、用户编辑优先、删除记录不复活、未选项不写false。

修改后运行README中的检查与测试。`tools/build_release.py`把当前live配置作为安装包的默认版本，不要求维护者手动复制两份配置；它只打包技能白名单目录，输出到被git忽略的dist目录。

程序版本在 `scripts/online_config.py` 的 `CLIENT_VERSION`。更改程序能力时更新版本和CHANGELOG，构建新包并发布Release。纯配置修改可保持客户端版本；建议更新配置中的 `version` 便于排查。新格式需要更高客户端时设置 `min_client`，旧客户端会保留旧缓存。

本仓库不自动给同事安装程序、不代替本人授权、不分享应用密钥。新增宿主或部署方式须在实际环境验证，未验证的范围写清楚。
