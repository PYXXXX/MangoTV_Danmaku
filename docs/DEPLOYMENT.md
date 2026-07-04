# 直播弹幕人气统计：完整部署手册

本文是服务器模式的统一部署文档，覆盖从空白 Linux 主机到可运营状态的完整流程：服务安装、基础配置、运营端密码、GitHub Pages、飞书 Bot、systemd、HTTPS、验收、备份、升级、回滚和排障。

浏览器扩展的本地安装见项目根目录 [README.md](../README.md)。精确结果的语义清洗规则属于 Agent 执行协议，继续单独维护在 [PRECISE_RESULT_AGENT.md](PRECISE_RESULT_AGENT.md)。

## 0. 部署结果与推荐拓扑

推荐生产形态是“单实例服务 + 本地持久化 + HTTPS 反向代理 + 飞书长连接 + GitHub Pages 公开页”。

~~~mermaid
flowchart LR
    MGTV["芒果 TV 弹幕接口"] --> SVC["vote_server.py<br/>单实例"]
    OP["运营浏览器"] -->|HTTPS + 登录密码| NGINX["Caddy / Nginx / 可信代理"]
    NGINX --> SVC
    FS["飞书运营群"] <-->|出站 WebSocket 长连接| SVC
    SVC --> DATA["/var/lib/mgtv-danmaku<br/>配置、状态、原始弹幕、SQLite 去重"]
    SVC -->|仅聚合结果| GH["GitHub Contents API"]
    GH --> PAGES["GitHub Actions / Pages<br/>公开结果页"]
~~~

关键边界：

- 运营端展示与操作接口由密码保护；正式环境仍建议放在 VPN、堡垒机或可信网络之后。
- 原始弹幕、昵称、数据库、`/var/lib/mgtv-danmaku/config.json` 不上传 GitHub。
- GitHub 只接收聚合后的 `site/data/results.json`。
- 飞书推荐使用出站 WebSocket 长连接，不需要公网回调地址。
- 当前状态和幂等数据存放在本机，正式环境只运行一个服务实例。

## 1. 前置条件

### 1.1 主机

- Linux 服务器，示例使用 Ubuntu/Debian 风格命令。
- Python 3.10 或更高版本。
- Git、Python venv 和基础 TLS/反向代理工具。
- 建议至少预留 2 GB 内存；磁盘容量按弹幕规模和保留周期评估。
- 服务器时区不影响数据格式；场次名称中的展示时间固定按北京时间生成。

安装基础软件：

~~~bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
~~~

如需 Nginx：

~~~bash
sudo apt install -y nginx
~~~

### 1.2 网络

服务器至少需要以下出站访问：

- 芒果 TV 弹幕接口：HTTPS。
- 飞书开放平台：HTTPS/WSS，仅启用飞书时需要。
- GitHub API：HTTPS，仅启用自动发布时需要。

入站访问按部署方式选择：

- 仅本机或 VPN 使用：无需把 8080 暴露到公网。
- 通过域名访问运营端：只开放反向代理的 80/443，8080 仅监听 `127.0.0.1`。
- 飞书 WebSocket 长连接：不需要开放入站回调端口。
- 飞书 HTTP 回调兼容模式：必须让 `/feishu/events` 可从飞书公网访问。

## 2. 创建服务用户并安装代码

以下示例统一安装到 `/opt/MangoTV_Danmaku`，服务用户为 `mgtv-vote`。

~~~bash
sudo useradd --system --create-home --home-dir /var/lib/mgtv-danmaku --shell /usr/sbin/nologin mgtv-vote
sudo git clone https://github.com/PYXXXX/MangoTV_Danmaku.git /opt/MangoTV_Danmaku
sudo chown -R mgtv-vote:mgtv-vote /opt/MangoTV_Danmaku
cd /opt/MangoTV_Danmaku
sudo -u mgtv-vote python3 -m venv .venv
sudo -u mgtv-vote .venv/bin/pip install --upgrade pip
sudo -u mgtv-vote .venv/bin/pip install -r requirements-server.txt
~~~

创建独立于源码目录的可写配置和数据目录：

~~~bash
sudo install -d -o mgtv-vote -g mgtv-vote -m 700 /var/lib/mgtv-danmaku
sudo install -d -o mgtv-vote -g mgtv-vote -m 700 /var/lib/mgtv-danmaku/data
sudo -u mgtv-vote cp server/config.example.json /var/lib/mgtv-danmaku/config.json
sudo chmod 600 /var/lib/mgtv-danmaku/config.json
~~~

生产环境使用 `/var/lib/mgtv-danmaku/config.json`。这样运营 WebUI 可以原子保存配置和备份，而源码目录在 systemd 的 `ProtectSystem=full` 下保持只读。本地开发仍可使用被 Git 忽略的 `server/config.json`。

## 3. 基础配置

编辑：

~~~bash
sudoedit /var/lib/mgtv-danmaku/config.json
~~~

### 3.1 监听地址

经 Nginx 或其他反向代理时，建议：

~~~json
{
  "listen": {
    "host": "127.0.0.1",
    "port": 8080,
    "public_base_url": "https://operator.example.com"
  }
}
~~~

仅在受控内网直接访问 8080 时才使用 `0.0.0.0`。不要在没有网络边界和登录密码的情况下把 8080 暴露到公网。

### 3.2 弹幕来源

~~~json
{
  "mgtv": {
    "url": "https://www.mgtv.com/z/1001668/5366.html",
    "history_api": "https://lb.bz.mgtv.com/get_history",
    "flag": "liveshow",
    "poll_seconds": 2.0,
    "reconnect_seconds": 5,
    "count_initial_history": false,
    "dedup_hot_cache_size": 200000,
    "dedup_max_records": 100000000,
    "dedup_db_path": "/var/lib/mgtv-danmaku/data/fingerprints.sqlite3"
  }
}
~~~

说明：

- 服务会从 `/z/{activityId}/{cameraId}.html` 解析 cameraId，并请求 `room_id=liveshow-{cameraId}`。
- 如页面 URL 无法解析，可在 `mgtv` 中显式增加 `"room_id": "liveshow-5366"`。
- `count_initial_history=false` 表示场次启动时先预热历史列表但不计票，避免把开场前缓存算入本轮。
- 去重索引主要占磁盘；`dedup_hot_cache_size` 控制内存中的热缓存规模。

### 3.3 活动、候选人与计票策略

~~~json
{
  "vote": {
    "activity": "歌手 2026",
    "multi_candidate_policy": "all",
    "candidates": [
      {"name": "张远", "aliases": ["张远", "远远"]},
      {"name": "窦靖童", "aliases": ["窦靖童", "童童"]}
    ]
  }
}
~~~

- 每行候选人的 `name` 是报表正式名。
- `aliases` 应包含正式名和允许匹配的别名。
- 同一个别名不能同时属于多位候选人。
- `multi_candidate_policy=all` 表示一条弹幕提及多人时每位都计 1 票。
- `multi_candidate_policy=review` 表示多人弹幕不进入实时票数，留给精确清洗审核。

候选人配置会在新建场次时复制到场次元数据。正式直播中途修改配置不会自动改写已存在的场次。

### 3.4 存储

默认配置：

~~~json
{
  "storage": {
    "directory": "/var/lib/mgtv-danmaku/data"
  }
}
~~~

持久化内容包括：

- `/var/lib/mgtv-danmaku/data/state.json`：活动、场次、票数和发布状态。
- `/var/lib/mgtv-danmaku/data/raw_messages.jsonl`：全量去重后的原始弹幕日志。
- `/var/lib/mgtv-danmaku/data/rounds/*.jsonl`：按场次追加的记录。
- `/var/lib/mgtv-danmaku/data/fingerprints.sqlite3`：持久化去重索引。

这些文件可能含昵称和原始弹幕，应按内部数据管理要求限制访问和保留周期。

### 3.5 运营端在线配置与热重载

登录运营 WebUI 后点击“系统配置”，可以在线维护节目、候选人、采集、去重、GitHub、飞书、运营密码及高级服务参数。保存时服务器会先校验完整配置，再以 600 权限原子写入，并保留一个 `config.json.bak`。

热应用规则：

- 立即生效：历史接口、轮询/重连、去重容量、GitHub 发布、密码策略和飞书连接。
- 下一场生效：默认活动、候选人、别名、多人策略、直播 URL、room_id 和首批历史策略。正在采集的场次保持启动时冻结的口径。
- 保存后需重启：监听地址、端口、数据目录、SQLite 去重文件路径。WebUI 会明确显示待重启字段，并在没有场次采集时提供“安全重启服务”按钮；systemd 自动拉起新进程。

正在采集时服务会拒绝重启动作。配置 API 永远不会回传 GitHub Token、飞书 Secret、密码哈希或会话密钥；敏感输入留空表示保留服务器现值。

### 3.6 运营端程序升级

登录运营 WebUI 后进入“系统配置 → 程序版本升级”，可以在线检查部署目录当前 commit 与远端目标分支 commit。发现新 commit 时，面板会提示是否立即升级。

自动升级流程：

1. 检查服务是否空闲。正在采集或有场次未结束时拒绝升级。
2. 检查 `/opt/MangoTV_Danmaku` 是否为干净 git 工作区。存在未提交或未跟踪文件时拒绝升级，避免覆盖现场修改。
3. 后台执行 `git fetch --progress` 并只允许 `--ff-only` 快进更新；如果本地与远端分叉，必须人工处理。
4. 使用当前服务进程的 Python 执行 `pip install -r requirements-server.txt`。
5. 完成后发送 `SIGTERM`，由 systemd 的 `Restart=always` 自动拉起新版本。

WebUI 会显示升级进度条、当前阶段、最近输出和拉取阶段的传输速度。进度来自 git/pip 命令输出，网络或远端没有提供速度时速度栏会显示 `-`。

这是一键在线升级，不是 Python 代码的内存级热替换，因此会有一次短暂重启。升级重启也会顺带让 WebUI 中已保存但标记“需重启”的配置生效。

## 4. 启用运营端密码

在项目目录运行：

~~~bash
sudo -u mgtv-vote .venv/bin/python tools/setup_operator_password.py \
  --config /var/lib/mgtv-danmaku/config.json
~~~

向导会：

- 要求至少 10 个字符并二次确认。
- 只保存 PBKDF2-SHA256 哈希，不保存明文密码。
- 生成随机会话签名密钥。
- 询问登录 Cookie 是否只允许通过 HTTPS 发送。
- 修改密码时轮换会话密钥，让旧登录立即失效。

选择规则：

- 本地 `http://127.0.0.1:8080` 调试：HTTPS-only Cookie 选择 `n`。
- 正式 HTTPS 域名：选择 `y`，或直接加 `--secure-cookie`。

可选参数：

~~~bash
sudo -u mgtv-vote .venv/bin/python tools/setup_operator_password.py \
  --config /var/lib/mgtv-danmaku/config.json \
  --session-hours 12 --secure-cookie
~~~

默认连续 5 次失败后，同一来源在 5 分钟窗口内被限制。反向代理后应用看到的来源通常是代理地址，因此多名运营人员可能共享该限制。

关闭密码保护：

~~~bash
sudo -u mgtv-vote .venv/bin/python tools/setup_operator_password.py \
  --config /var/lib/mgtv-danmaku/config.json --disable
~~~

每次修改后都要重启服务。正式环境不建议关闭。

受保护路径：

- `/`、`/admin`、运营端资源和清洗规范。
- `/api/*`、切片下载、指令接口和精确结果上传。

保持公开的路径：

- `/login`、`/auth/login`。
- `/healthz`。
- `/feishu/events`。
- 登录页所需样式文件。

## 5. 配置 GitHub Pages 公开结果页

如果不需要公开页面，保持 `github.enabled=false`，可以跳过本节。

### 5.1 GitHub 仓库与 Pages

仓库内已包含 `.github/workflows/pages.yml`，它在 `site/**` 更新后部署静态页面。

在目标仓库中：

1. 打开 Settings → Pages。
2. 将 Build and deployment 的 Source 设为 GitHub Actions。
3. 确认默认分支和配置中的 `github.branch` 一致。
4. 首次可手动触发 `Deploy public vote board` 工作流验证 Pages。

### 5.2 创建最小权限 Token

建议创建 fine-grained personal access token：

1. Repository access 只选择目标仓库。
2. Repository permissions 只授予 Contents: Read and write。
3. 设置合理的过期时间。
4. 不要把 token 写入示例配置、日志、聊天或仓库。

### 5.3 服务端发布配置

~~~json
{
  "github": {
    "enabled": true,
    "owner": "your-github-owner",
    "repo": "MangoTV_Danmaku",
    "branch": "main",
    "path": "site/data/results.json",
    "token": "github_pat_xxx"
  }
}
~~~

服务通过 GitHub Contents API 更新指定文件。发布动作只写聚合状态，不包含原始弹幕、昵称、密码哈希或飞书密钥。

GitHub Pages 属于分钟级近实时：最终延迟由发布动作、Actions 排队和静态页面轮询共同决定。大型直播应准备公司自有 API、对象存储或 CDN 镜像作为备用。

## 6. 配置飞书交互卡片 Bot

如果不使用飞书遥控，保持 `feishu.enabled=false`，可以跳过本节。

### 6.1 推荐：在运营 WebUI 一键绑定

服务启动并登录运营 WebUI 后：

1. 打开“系统配置 → 飞书 Bot”。
2. 点击“一键绑定飞书”里的“发起飞书绑定”。
3. 在新打开的飞书授权页按提示完成授权/安装；如果浏览器拦截弹窗，就手动点击页面显示的授权链接。
4. 回到 WebUI 等待状态变为“已绑定”。
5. 点击“保存并热应用”（如需调整公开结果页 URL 或白名单）。

绑定成功后，服务会自动写入：

- `feishu.enabled=true`。
- `feishu.connection_mode=websocket`。
- 飞书返回的 `app_id` / `app_secret`。
- 授权人的 `open_id`（加入 `allowed_open_ids`，便于立即私聊测试）。
- 若 `public_results_url` 为空，会使用 `listen.public_base_url` 作为默认公开结果页。

`app_secret` 只保存在 `/var/lib/mgtv-danmaku/config.json`，WebUI 和 API 都不会回显。保存使用原子写入，目标文件权限为 `600`，并会保留 `config.json.bak`。

随后把 Bot 添加到运营群，在群里发送“我的ID”获取 `chat_id`，填入 WebUI 的 `allowed_chat_ids` 后保存。正式节目不要保留 `*`；两个白名单都为空也会兼容性地允许所有可触达 Bot 的用户操作。

这个流程复用了飞书官方 `larksuite/cli config init --new` 的授权注册方式。如果企业租户策略阻止自动注册，WebUI 会显示失败原因，此时使用下面的手动兜底方式。

### 6.2 手动兜底：开放平台配置或 CLI 向导

如需手动创建企业自建应用：

1. 在飞书开放平台创建企业自建应用。
2. 启用“机器人”能力。
3. 至少申请以下权限：
   - `im:message.p2p_msg:readonly`：接收私聊消息。
   - `im:message.group_at_msg:readonly`：接收群内 @机器人消息。
   - `im:message:send_as_bot`：以机器人身份发送消息和卡片。
4. 在“事件与回调”中，把事件订阅方式和回调订阅方式都设为“使用长连接接收”。
5. 添加事件 `im.message.receive_v1`。
6. 添加回调 `card.action.trigger`。
7. 创建并发布应用版本；按企业流程完成管理员审核。
8. 把 Bot 加入运营群，或直接与 Bot 私聊。

缺少 `card.action.trigger` 时，卡片能显示但按钮不会执行。

也可以运行配置向导：

~~~bash
cd /opt/MangoTV_Danmaku
sudo -u mgtv-vote .venv/bin/python tools/setup_feishu_bot.py \
  --config /var/lib/mgtv-danmaku/config.json
~~~

向导会写入：

- `app_id`、`app_secret`。
- 推荐的 `connection_mode=websocket`。
- 运营人员 `allowed_open_ids`。
- 运营群 `allowed_chat_ids`。
- 公开结果页 `public_results_url`。

首次不知道 open_id/chat_id 时：

1. 在向导选择“首次联调”，临时写入 `*`。
2. 启动服务。
3. 私聊或在运营群 @Bot 发送“我的ID”。
4. 记录返回的 open_id/chat_id。
5. 重新运行向导，选择“正式使用”，写入精确白名单。

### 6.3 可用操作

发送“菜单”“卡片”或“控制台”打开交互卡片。卡片支持：

- 开始默认场次。
- 结束本轮并发布粗略结果。
- 刷新状态和票数。
- 查看、切换场次。
- 手动发布粗略结果。
- 打开公开结果页。

文本指令：

~~~text
帮助
开始 <活动名>|<场次名> [直播URL]
结束
状态
结果 [场次名/ID]
场次
切换 <场次名/ID>
命名 <新名称>
发布粗略
候选人
我的ID
~~~

精确结果文件仍在运营 WebUI 上传。

### 6.4 HTTP 回调兼容模式

仅在无法使用长连接时，把 `connection_mode` 改为 `webhook`，配置 `verification_token`，并在飞书开放平台填写：

~~~text
https://operator.example.com/feishu/events
~~~

兼容端点要求公网 HTTPS，且当前只处理未加密事件体。如果企业要求 `encrypt_key`，使用推荐的 WebSocket 长连接模式。

## 7. 前台启动与首次验收

先以前台方式启动，便于直接看到错误：

~~~bash
cd /opt/MangoTV_Danmaku
sudo -u mgtv-vote .venv/bin/python server/vote_server.py \
  --config /var/lib/mgtv-danmaku/config.json
~~~

正常日志至少包含：

~~~text
vote server listening on 127.0.0.1:8080
~~~

启用飞书长连接时还会出现：

~~~text
feishu bot connected with WebSocket long connection
~~~

另开终端检查：

~~~bash
curl -fsS http://127.0.0.1:8080/healthz
curl -I http://127.0.0.1:8080/
~~~

预期：

- `/healthz` 返回 HTTP 200 和 `"ok": true`。
- 启用密码后访问 `/` 返回 302 跳转到 `/login`。
- 未登录请求 `/api/results.json` 返回 401。
- 登录后可打开运营端、创建测试场次、结束场次并导出 JSONL。
- 飞书发送“菜单”能显示卡片，点击“刷新状态”能更新。
- 启用 GitHub 后，“发布粗略结果”会返回 GitHub 提交链接。

前台验证结束后按 Ctrl+C 停止，再启用 systemd。

## 8. 使用 systemd 常驻

仓库提供 [mgtv-danmaku.service.example](../deploy/mgtv-danmaku.service.example)。如果使用本文默认路径和用户，可直接复制；否则先修改 `User`、`Group`、`WorkingDirectory`、`ExecStart` 和 `ReadWritePaths`。

~~~bash
cd /opt/MangoTV_Danmaku
sudo cp deploy/mgtv-danmaku.service.example /etc/systemd/system/mgtv-danmaku.service
sudo systemctl daemon-reload
sudo systemctl enable --now mgtv-danmaku
sudo systemctl status mgtv-danmaku
~~~

查看日志：

~~~bash
journalctl -u mgtv-danmaku -f
~~~

常用命令：

~~~bash
sudo systemctl restart mgtv-danmaku
sudo systemctl stop mgtv-danmaku
sudo systemctl start mgtv-danmaku
~~~

服务示例启用了 `ProtectSystem=full`，源码目录保持只读，只允许服务在 `/var/lib/mgtv-danmaku` 保存配置、备份和数据。大多数配置由 WebUI 热应用；只有界面标记“需重启”的字段需要重启服务。

## 9. HTTPS 反向代理（Caddy / Nginx）

正式环境建议让服务只监听 `127.0.0.1:8080`，由现有反向代理终止 TLS。

### 9.1 Caddy

已有 Caddy 时只新增独立站点，不改写其他域名：

~~~caddyfile
danmaku.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
~~~

校验并无中断重载：

~~~bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
~~~

Caddy 会在 DNS 正确且 80/443 可达时自动申请证书。

### 9.2 Nginx

示例 `/etc/nginx/sites-available/mgtv-danmaku`：

~~~nginx
server {
    listen 80;
    server_name operator.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name operator.example.com;

    ssl_certificate /etc/letsencrypt/live/operator.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/operator.example.com/privkey.pem;

    client_max_body_size 3m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;
    }
}
~~~

启用并检查：

~~~bash
sudo ln -s /etc/nginx/sites-available/mgtv-danmaku /etc/nginx/sites-enabled/mgtv-danmaku
sudo nginx -t
sudo systemctl reload nginx
~~~

注意：

- 证书签发方式由所在组织决定；先准备有效证书再启用 443 配置。
- 使用 HTTPS 后重新运行密码向导，确保 `secure_cookie=true`。
- 防火墙只开放必要的 SSH、HTTP/HTTPS；不要公开 8080。
- 飞书 WebSocket 是服务主动建立的出站连接，不需要在 Nginx 配置 WebSocket Upgrade。
- 如果使用飞书 HTTP 回调并在 Nginx 前再加一层统一认证，必须单独放行 `/feishu/events`，应用自身的运营密码中间件已经放行该路径。

## 10. 上线验收清单

### 服务与数据

- [ ] Python 依赖安装成功。
- [ ] `/var/lib/mgtv-danmaku/config.json` 权限为 600，所有者为服务用户。
- [ ] `/var/lib/mgtv-danmaku/data` 可写，源码目录保持只读。
- [ ] `/healthz` 返回 200。
- [ ] 创建、结束、重命名、导出场次均正常。
- [ ] 停止并重启服务后，历史场次仍存在。
- [ ] 初始历史弹幕没有被误算入新场次。

### 访问安全

- [ ] 运营端必须登录。
- [ ] 错误密码不会泄露更多信息。
- [ ] HTTPS 环境的 Cookie 带 Secure。
- [ ] 8080 未暴露公网。
- [ ] 配置、token、原始弹幕未进入 Git。
- [ ] 运营密码、GitHub token、飞书密钥有明确轮换责任人。

### 飞书

- [ ] 应用版本已发布并通过审核。
- [ ] 消息事件和卡片回调均使用长连接。
- [ ] `im.message.receive_v1` 与 `card.action.trigger` 已添加。
- [ ] “菜单”和卡片按钮正常。
- [ ] 白名单已从 `*` 收紧到真实 open_id/chat_id。
- [ ] 只运行一个连接同一飞书应用的服务实例。

### GitHub Pages

- [ ] Token 只具备目标仓库 Contents 写权限。
- [ ] `site/data/results.json` 能被服务更新。
- [ ] Pages 工作流成功。
- [ ] 公开页只含聚合数据。
- [ ] 已评估 GitHub Pages 延迟和中国内地可达性，并准备备用入口。

## 11. 日常运营流程

1. 登录运营端或在飞书打开控制卡片。
2. 核对活动名、候选人和直播 URL。
3. 开始新场次。
4. 观察样本量、实时票数和语义待审数。
5. 结束场次；服务锁定切片并把北京时间范围追加到场次名。
6. 需要快速展示时发布粗略结果。
7. 需要精确结果时导出 JSONL，按第 14 节清洗后上传。
8. 核对公开页，确认结果版本和场次名称。
9. 按保留策略备份或清理原始数据。

## 12. 备份与恢复

### 12.1 需要备份的内容

最低集合：

- `/var/lib/mgtv-danmaku/config.json`。
- `/var/lib/mgtv-danmaku/data/` 整个目录。

可选：

- `config/program_context.md`。
- 内部清洗输出和审核记录。
- Caddy/Nginx 与 systemd 的本机配置。

备份中包含密钥、昵称和原始弹幕，必须限制权限并按需要加密。

### 12.2 一致性备份

停止服务后打包最稳妥：

~~~bash
sudo systemctl stop mgtv-danmaku
cd /opt/MangoTV_Danmaku
sudo mkdir -p /var/backups
sudo tar -czf /var/backups/mgtv-danmaku-<DATE>.tar.gz -C /var/lib mgtv-danmaku
sudo chmod 600 /var/backups/mgtv-danmaku-<DATE>.tar.gz
sudo systemctl start mgtv-danmaku
~~~

### 12.3 恢复

~~~bash
sudo systemctl stop mgtv-danmaku
sudo tar -xzf /var/backups/mgtv-danmaku-<DATE>.tar.gz -C /var/lib
sudo chown -R mgtv-vote:mgtv-vote /var/lib/mgtv-danmaku
sudo chmod 600 /var/lib/mgtv-danmaku/config.json
sudo systemctl start mgtv-danmaku
sudo systemctl status mgtv-danmaku
~~~

恢复后检查 `/healthz`、历史场次、飞书连接和公开发布。

## 13. 升级与回滚

### 13.1 升级

推荐方式是在运营 WebUI 的“系统配置 → 程序版本升级”里检查并一键升级。WebUI 会做空闲检查、脏工作区检查、fast-forward 限制、依赖安装、进度显示和自动重启。

如果需要手动升级，先备份，再更新代码和依赖：

~~~bash
sudo systemctl stop mgtv-danmaku
cd /opt/MangoTV_Danmaku
sudo -u mgtv-vote git pull --ff-only
sudo -u mgtv-vote .venv/bin/pip install -r requirements-server.txt
sudo -u mgtv-vote .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
sudo systemctl start mgtv-danmaku
sudo systemctl status mgtv-danmaku
~~~

比较 `server/config.example.json` 与本机配置，补充新字段，但不要用示例文件覆盖真实配置。

### 13.2 代码回滚

保留 `/var/lib/mgtv-danmaku/config.json` 和数据目录，只切换代码：

~~~bash
sudo systemctl stop mgtv-danmaku
cd /opt/MangoTV_Danmaku
sudo -u mgtv-vote git switch --detach <KNOWN_GOOD_COMMIT>
sudo -u mgtv-vote .venv/bin/pip install -r requirements-server.txt
sudo systemctl start mgtv-danmaku
~~~

如果新版已经写入不兼容数据，应同时恢复升级前备份。回到主分支：

~~~bash
sudo systemctl stop mgtv-danmaku
cd /opt/MangoTV_Danmaku
sudo -u mgtv-vote git switch main
sudo -u mgtv-vote git pull --ff-only
sudo systemctl start mgtv-danmaku
~~~

## 14. 精确结果清洗与发布

部署手册只描述运行链路；计票语义、审计字段和上传格式以 [PRECISE_RESULT_AGENT.md](PRECISE_RESULT_AGENT.md) 为准。

准备节目背景：

~~~bash
cp config/program_context.example.md config/program_context.md
~~~

从运营端下载场次 JSONL，或在服务器导出：

~~~bash
.venv/bin/python tools/export_round_slice.py   --data-dir /var/lib/mgtv-danmaku/data   --round "第一轮"   --out output/round-1.jsonl
~~~

执行规则清洗：

~~~bash
.venv/bin/python tools/offline_clean.py output/round-1.jsonl   --context config/program_context.md   --out output
~~~

只把 `output/codex_prompt.md` 指定的 `review_batches` 交给 Codex，生成 `output/codex_decisions.jsonl`，然后合并：

~~~bash
.venv/bin/python tools/merge_results.py output
~~~

只有以下两个值都为 0 时才发布：

- `unresolvedReviewMessages`。
- `invalidDecisionLines`。

在运营端选择已结束场次，上传生成的 `precise_result.json` 或 `precise_result.xml`。服务校验通过后发布精确结果，公开页默认优先展示精确结果。

## 15. 故障排查

### 服务无法启动

~~~bash
sudo systemctl status mgtv-danmaku
journalctl -u mgtv-danmaku -n 200 --no-pager
~~~

检查：

- `/var/lib/mgtv-danmaku/config.json` 是否为合法 JSON。
- Python 依赖是否安装在项目 `.venv`。
- 8080 是否已被占用。
- `/var/lib/mgtv-danmaku/data` 与 SQLite 文件是否归服务用户所有。
- systemd 路径是否与实际安装目录一致。
- 启用密码后是否存在 `password_hash` 和 `session_secret`。

### 密码正确但不断回到登录页

通常是 `secure_cookie=true`，但正在使用 HTTP 访问。通过 HTTPS 访问，或在本地重新运行：

~~~bash
sudo -u mgtv-vote .venv/bin/python tools/setup_operator_password.py \
  --config /var/lib/mgtv-danmaku/config.json --insecure-cookie
sudo systemctl restart mgtv-danmaku
~~~

### 飞书长连接未启动

检查：

- `feishu.enabled=true`。
- `app_id/app_secret` 是否正确。
- `lark-oapi` 是否安装。
- 飞书应用版本是否已发布。
- 服务器是否允许出站 HTTPS/WSS。
- 日志是否出现 SDK 鉴权或网络错误。

### 飞书卡片显示但按钮无效

确认已添加 `card.action.trigger`，且回调订阅方式也选择“使用长连接接收”。

### 飞书提示无操作权限

临时使用向导的首次联调模式，发送“我的ID”获取真实 open_id/chat_id，再写入精确白名单。完成后不要保留 `*`。

### 没有采集到弹幕

检查：

- 直播 URL 的 cameraId 是否正确。
- 必要时显式配置 `mgtv.room_id`。
- `history_api` 是否仍可访问。
- 开始场次后是否只有预热请求；`count_initial_history=false` 时第一批历史不会计票。
- 日志中是否有重连或接口错误。
- 仍无法定位时阅读 [客户端接口排查笔记](../server/interface_notes.md)。

### GitHub 发布失败

- 401：token 无效或过期。
- 403：token 没有目标仓库 Contents 写权限，或组织策略阻止。
- 404：owner/repo/branch/path 错误，或 token 无权看到仓库。
- 发布成功但页面没更新：检查 Actions 和 Pages 环境状态。
- 多次并发发布冲突：确认只运行一个服务实例。

### 磁盘持续增长

重点检查：

- `raw_messages.jsonl`。
- `rounds/*.jsonl`。
- `fingerprints.sqlite3`。
- 清洗输出和备份文件。

制定按节目、场次和合规要求执行的归档/删除策略。不要在服务运行时直接截断 SQLite 或当前日志。

## 16. HTTP 路径速查

| 方法 | 路径 | 未登录可用 | 用途 |
|---|---|---:|---|
| GET | `/`、`/admin` | 否 | 运营 WebUI |
| GET | `/login` | 是 | 登录页 |
| POST | `/auth/login` | 是 | 提交密码 |
| POST | `/auth/logout` | 否 | 退出登录 |
| GET | `/healthz` | 是 | 健康检查 |
| GET | `/api/results.json` | 否 | 当前聚合状态 |
| GET | `/api/settings` | 否 | 读取已脱敏的在线配置 |
| POST | `/api/settings` | 否 | 校验、保存并热应用配置 |
| GET | `/api/feishu/binding` | 否 | 读取飞书一键绑定状态 |
| POST | `/api/feishu/binding/start` | 否 | 发起飞书授权绑定 |
| POST | `/api/restart` | 否 | 无活动场次时安全重启服务 |
| GET | `/api/update/status` | 否 | 检查当前 commit、远端 commit 与升级进度 |
| POST | `/api/update/apply` | 否 | 空闲时启动后台快进升级、更新依赖并自动重启 |
| GET | `/api/rounds/{id}.jsonl` | 否 | 导出场次切片 |
| POST | `/api/rounds/{id}/precise-result` | 否 | 上传精确结果 |
| POST | `/api/command` | 否 | 执行运营指令 |
| GET | `/docs/precise-result-agent` | 否 | 清洗规范 |
| POST | `/feishu/events` | 是 | 飞书 HTTP 回调兼容端点 |

当 `operator_auth.enabled=false` 时，运营路径不会要求登录；这只适用于受控本地调试。
