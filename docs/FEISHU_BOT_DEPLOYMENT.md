# 飞书交互卡片 Bot 部署

本项目推荐使用飞书官方 SDK 的 WebSocket 长连接接收消息事件和卡片回调。它与 HTTP 回调相比不需要公网域名、TLS 证书或开放入站端口，适合节目现场和普通云服务器。运营 WebUI 是否对外暴露，与飞书 Bot 连接无关。

## 1. 飞书应用配置

1. 在飞书开放平台创建企业自建应用并启用“机器人”能力。
2. 在权限管理中至少申请：
   - `im:message.p2p_msg:readonly`：接收私聊消息。
   - `im:message.group_at_msg:readonly`：接收群内 @机器人消息。
   - `im:message:send_as_bot`：以机器人身份发送文本和交互卡片。
3. 在“事件与回调”中，把事件订阅方式和回调订阅方式都设为“使用长连接接收”。
4. 添加事件 `im.message.receive_v1`。
5. 添加回调 `card.action.trigger`。缺少该回调时，卡片按钮无法执行操作。
6. 创建应用版本并发布；企业租户通常还需要管理员审核。
7. 把机器人加入运营群，或直接与机器人私聊。

## 2. 服务端配置

安装依赖并运行交互式配置向导：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt
python tools/setup_feishu_bot.py
```

向导会从 `server/config.example.json` 创建或更新本机 `server/config.json`，逐项提示：

- `app_id`：飞书开放平台 → 企业自建应用 → 凭证与基础信息 → App ID。
- `app_secret`：同一页面的 App Secret，输入时不会回显。
- `public_results_url`：飞书卡片“打开公开结果页”按钮使用的地址。
- `allowed_open_ids` / `allowed_chat_ids`：限制可操作 Bot 的运营人员和运营群。

首次联调还不知道 `open_id` 和 `chat_id` 时，可以在向导里选择“首次联调”，临时写入 `*`；启动服务后向 Bot 发送“我的ID”，Bot 会回显当前来源 ID。拿到真实 ID 后重新运行：

```bash
python tools/setup_feishu_bot.py
```

并选择“正式使用”，填入回显的 `open_id` 与 `chat_id`。最终 `server/config.json` 中的飞书配置大致为：

```json
{
  "feishu": {
    "enabled": true,
    "connection_mode": "websocket",
    "app_id": "cli_xxx",
    "app_secret": "你的应用密钥",
    "allowed_open_ids": ["ou_运营人员ID"],
    "allowed_chat_ids": ["oc_运营群ID"],
    "public_results_url": "https://your-name.github.io/MangoTV_Danmaku/"
  }
}
```

- `allowed_open_ids` 与 `allowed_chat_ids` 用于限制可执行运营操作的用户和群。建议正式环境明确填写，不使用 `*`。
- 两个白名单都省略时，为兼容旧配置会允许所有能访问机器人的用户操作，不建议用于正式节目。
- WebSocket 模式不使用 `verification_token`；该字段只供 HTTP 回调兼容模式使用。
- `app_secret`、GitHub token 和原始弹幕均只保存在服务器，不提交到仓库。
- 配置向导会把 `server/config.json` 权限设为仅当前用户可读写；覆盖已有配置时会生成 `server/config.json.bak-时间戳` 备份，备份文件也已被 Git 忽略。

## 3. 卡片操作范围

向机器人发送“菜单”“卡片”或“控制台”即可获得控制卡片。卡片支持：

- 开始默认场次：使用 `vote.activity` 和自动场次名。
- 结束本轮并发布粗略结果。
- 刷新状态与实时票数。
- 查看场次列表并切换所选场次。
- 手动发布粗略结果。
- 打开公开结果页。

需要输入自定义内容的操作继续使用文本指令：

```text
开始 歌手 2026|第一轮·在线观众选择 https://www.mgtv.com/z/1001668/5366.html
命名 第一轮·在线观众选择
```

精确结果文件仍应在运营 WebUI 上传，因为飞书卡片按钮不承担本地文件校验和上传。

## 4. 启动与验证

前台验证：

```bash
source .venv/bin/activate
python server/vote_server.py --config server/config.json
```

正常启动时会看到：

```text
vote server listening on 0.0.0.0:8080
feishu bot connected with WebSocket long connection
```

随后私聊机器人发送“菜单”，确认卡片可以显示；点击“刷新状态”，确认卡片原地更新。

如果使用了首次联调白名单，继续发送“我的ID”，记录 Bot 返回的 `open_id` 和 `chat_id`，再重新运行配置向导锁定正式白名单。

## 5. systemd 常驻部署

仓库提供 [deploy/mgtv-danmaku.service.example](../deploy/mgtv-danmaku.service.example)。按实际路径修改 `User`、`Group`、`WorkingDirectory` 与 `ExecStart` 后执行：

```bash
sudo cp deploy/mgtv-danmaku.service.example /etc/systemd/system/mgtv-danmaku.service
sudo systemctl daemon-reload
sudo systemctl enable --now mgtv-danmaku
sudo systemctl status mgtv-danmaku
journalctl -u mgtv-danmaku -f
```

服务器需要允许出站 HTTPS/WSS 访问飞书开放平台；长连接模式不要求开放飞书回调入站端口。管理端口 `8080` 建议只允许 VPN、堡垒机或反向代理鉴权后的运营人员访问。

同一个飞书应用在多个服务实例上同时建立长连接时，事件可能被分发到不同实例。当前状态存储是本地文件与 SQLite，因此正式部署应保持单实例；如需高可用，应先把状态和幂等锁迁移到共享数据库。

## 6. HTTP 回调兼容模式

若必须使用 HTTP 回调，把 `connection_mode` 改为 `webhook`，并在飞书开放平台配置：

```text
https://你的受信任域名/feishu/events
```

此模式要求有效 HTTPS、可公网访问的回调地址和 `verification_token`。当前兼容端点只处理未加密事件体；如果企业要求配置 `encrypt_key`，请使用推荐的长连接模式。HTTP 模式仍支持消息事件和 `card.action.trigger`，但不是本项目推荐路径。

## 参考资料

- [飞书卡片概述](https://open.feishu.cn/document/feishu-cards/feishu-card-overview)
- [飞书官方 Python SDK](https://github.com/larksuite/oapi-sdk-python)
- [cc-connect 飞书长连接与卡片参考实现](https://github.com/chenhg5/cc-connect/tree/main/platform/feishu)
