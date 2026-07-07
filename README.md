# 直播弹幕投票统计

> 本项目以个人名义开源。统计数据不代表湖南卫视 & 芒果 TV 立场，仅供娱乐参考。

一个面向直播运营的双模式工具：

生产环境请从 [完整部署手册](docs/DEPLOYMENT.md) 开始；该文档统一包含服务器、运营端密码、GitHub Pages、飞书 Bot、systemd、HTTPS、备份升级和排障步骤。

1. **实时模式**：Chrome 扩展观察直播页热聊节点，艺人名或别名命中后立即计票，并展示实时排名。
2. **离线语义模式**：弹幕先落成 JSONL；本地规则完成绝大多数明确票，只把否定、比较、多人、泛称等歧义样本交给 Codex，最后合并票数。
3. **服务器模式**：Python 服务端直接调用客户端同款弹幕历史接口，可由飞书 Bot 遥控开始/结束/发布，不依赖前端电脑或 Chrome。
4. **公开结果页**：聚合票数可同步到 GitHub 仓库，由 GitHub Actions 自动部署到 `github.io`；不会公开昵称和原始弹幕。
5. **录制后处理**：运营无法实时盯直播时，可全程录制视频和弹幕，回看打标、截取片段，再导出片段弹幕或生成分析场次。

服务器模式采用“活动 → 场次”两级分类。活动可填写节目名（如“歌手 2026”）；场次名称保持运营命名，采集时间范围作为独立字段展示和导出，例如：

```text
第一轮
采集时间：2026/07/04 21:30:54 – 21:35:18
```

当前已在以下页面结构上验证：

- 官方活动页：`https://www.mgtv.com/z/{activityId}.html?...`
- 直播页：`https://www.mgtv.com/z/{activityId}/{cameraId}.html`
- 弹幕正文：`.u-hotchat-list .barrageContent`
- 昵称：同一 `li` 内的 `.u-hc-name`

Chrome 扩展模式依赖 DOM；服务器模式默认直接调用客户端接口：

- 历史弹幕：`https://lb.bz.mgtv.com/get_history?room_id=liveshow-{cameraId}`
- 当前页面示例：`room_id=liveshow-5366`

如果未来客户端接口变更，只需调整 [server/config.example.json](server/config.example.json) 的 `mgtv.history_api` 和 `mgtv.flag/camera_id/room_id`。

服务端在“检测播放源”和“开始场次”前会尝试自动刷新官方活动页并解析机位；如果直播尚未开始、页面没有暴露 cameraId，会提示稍后重试或手动填写带 cameraId 的直播页。

接口排查细节见 [server/interface_notes.md](server/interface_notes.md)。

## 一、安装扩展

1. Chrome 打开 `chrome://extensions/`。
2. 打开右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”，选择本项目的 `extension` 文件夹。
4. 打开或刷新芒果 TV 直播页面。
5. 点击扩展图标，按“一行一位艺人”的格式配置：

```text
张远, 远远
窦靖童, 童童
陈楚生, 陈老师
妮达
```

每行首项是报表正式名，后续项是别名。给轮次填写名称后点击“开始新一轮”，扩展会先读取当前保留的热聊，再持续接收新增弹幕。单条弹幕重复同一个名字多次，只给该艺人计 1 票。

“一条弹幕提到多人”有两种策略：

- **每位都计 1 票**：适合“提及即计票”的简单口径。
- **实时暂不计**：多人弹幕进入离线 Codex 审核，适合正式结果。

点击“结束并保存本轮”会立即停止计票、保存所有缓冲消息并展示本轮排名。历史场次可在下拉列表中切换、重命名和分别导出；实时大屏也支持场次切换。

点击“导出所选场次”会保存该轮元数据、原始昵称、正文、规则命中和采集时间。

## 二、服务器模式 + 飞书遥控

服务器模式适合录制现场：不打开浏览器、不依赖前端电脑性能，只轮询客户端同款弹幕接口并本地去重计票。

### 安装与启动

以下命令仅用于本地快速验证。正式部署请按 [完整部署手册](docs/DEPLOYMENT.md) 执行。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt
cp server/config.example.json server/config.json
python server/vote_server.py --config server/config.json
```

如果要启用飞书 Bot 遥控，推荐启动服务后在运营 WebUI 的“系统配置 → 飞书 Bot → 一键绑定飞书”中完成授权；本地调试也可以运行 `python tools/setup_feishu_bot.py` 手动更新配置。

建议同时为运营 WebUI 设置登录密码：

```bash
python tools/setup_operator_password.py
```

向导不会保存明文密码；它会写入 PBKDF2 哈希与随机会话密钥。改密会让旧会话立即失效，配置完成后需要重启服务。

启动后打开 `http://服务器地址:8080/` 即可进入管理 WebUI，风格与公开结果页一致，可开始/结束场次、重命名、发布粗略结果、查看排名、导出切片，以及上传并发布清洗后的精确结果。

可用 HTTP 接口：

- `GET /healthz`：健康检查。
- `GET /api/results.json`：当前公开聚合结果，格式与 `site/data/results.json` 一致。
- `GET /api/update/status`：检查当前 commit、远端 commit 与升级进度。
- `POST /api/update/apply`：空闲时启动后台快进升级、更新依赖并自动重启。
- `GET /api/feishu/binding`：读取飞书一键绑定状态（不返回 App Secret）。
- `POST /api/feishu/binding/start`：发起飞书授权绑定，返回授权链接与授权码。
- `GET /api/rounds/{round_id}.jsonl`：导出某个场次的 JSONL 切片，包含 meta 与该场次消息。
- `POST /api/rounds/{round_id}/precise-result`：通过 multipart 的 `file` 字段上传并发布 `.json` 或 `.xml` 精确结果。
- `POST /api/command`：本地调试指令，例如 `{"text":"开始 第一轮"}`。
- `POST /feishu/events`：飞书事件订阅回调地址。

启用 `operator_auth` 后，运营页面、清洗规范和 `/api/*` 均要求登录；`/healthz`、登录入口与飞书回调保持可访问。

登录后点击“系统配置”可在线维护活动、候选人、别名、多人策略、直播源、采集/去重、GitHub、飞书与密码策略，并可检查远端新 commit 后一键升级程序；升级时会显示当前阶段、进度条、最近输出和拉取速度。大多数配置立即热应用；当前场次的候选人口径保持冻结，监听地址、端口、数据目录、SQLite 路径和程序升级由界面提示安全重启后生效。

### 运营端密码保护

运行 `python tools/setup_operator_password.py` 后按提示输入并确认密码。默认会话时长为 12 小时，连续 5 次输错后同一来源会被限制 5 分钟。

本地 HTTP 调试时对“仅通过 HTTPS 提交登录 Cookie”回答 `n`；部署到 HTTPS 域名时回答 `y`。详细配置与排障见 [完整部署手册的运营端密码章节](docs/DEPLOYMENT.md#4-启用运营端密码)。

### 关键配置

`server/config.json` 中：

- `mgtv.url`：直播页链接，服务会自动从 `/z/{activityId}/{cameraId}.html` 解析 cameraId。
- `mgtv.room_id`：如需绕过解析，可直接填 `liveshow-5366`。
- `mgtv.count_initial_history`：默认 `false`，开始场次时先预热一次历史列表但不计票，避免把开场前缓存弹幕算入本轮。
- `mgtv.dedup_hot_cache_size`：内存热去重缓存大小，默认 `200000`。
- `mgtv.dedup_max_records`：SQLite 去重索引上限，默认 `100000000`，用于支撑超大场次且控制内存占用。
- `mgtv.dedup_db_path`：SQLite 去重索引位置，默认 `server/data/fingerprints.sqlite3`。
- `vote.activity`：默认活动名，例如 `歌手 2026`。
- `vote.candidates`：候选人与别名。
- `github`：与扩展版相同，用于发布聚合结果到 `site/data/results.json`。
- `operator_auth`：运营端密码哈希、会话有效期、HTTPS Cookie 和登录失败限速。

### 飞书 Bot 遥控

飞书“自定义机器人 webhook”只能发消息，不能接收运营指令；遥控管理需要飞书企业自建应用。本项目默认使用官方 SDK 的 WebSocket 长连接，不要求公网回调地址。

推荐路径：打开运营 WebUI → “系统配置” → “飞书 Bot” → “一键绑定飞书”，点击授权链接并按飞书页面完成授权/安装。绑定成功后系统会自动保存 `app_id` / `app_secret`、启用 WebSocket 长连接并热重载；`app_secret` 不会回显到页面。授权人的 `open_id` 会自动加入白名单，便于立即私聊 Bot 测试。

完整卡片按钮交互需要企业自建应用已配置 `card.action.trigger` 卡片回调。如果飞书提示“尚未配置卡片回调”，点击“去配置”又提示“该应用不存在”，通常表示一键绑定拿到的是 CLI/PersonalAgent 风格应用，不是企业开放平台里可管理的自建应用；请改用企业自建应用的 `app_id/app_secret` 手动填入 WebUI。

随后把 Bot 加入运营群，在群里发送“我的ID”获取 `chat_id`，填入 WebUI 的 `allowed_chat_ids` 后保存。向 Bot 发送任意消息即可刷新运营控制台卡片，可点击开始默认场次、结束、刷新、查看/切换场次和发布粗略结果。自定义活动名、候选人与直播源建议在 WebUI 配置；精确结果文件仍在运营 WebUI 上传。

手动兜底：本地运行 `python tools/setup_feishu_bot.py` 可交互式生成 `server/config.json`：向导会说明每个 ID 去哪里找，并支持首次联调临时写入 `*`。连通后向 Bot 发送“我的ID”，拿到 `open_id` / `chat_id` 后再重跑向导切换为正式白名单。

完整权限、白名单、systemd 常驻和 HTTP 回调兼容方案见 [完整部署手册的飞书章节](docs/DEPLOYMENT.md#6-配置飞书交互卡片-bot)。

支持指令：

```text
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
```

例子：

```text
开始 歌手 2026|第一轮·在线观众选择 https://www.mgtv.com/z/1001668/5366.html
状态
结束
发布粗略
```

服务器模式的去重指纹为 `用户标识 + 昵称 + 内容`。这能降低重复刷屏影响，但如果同一用户在短时间内重复发送完全相同内容，会按一条计。去重索引采用“内存热缓存 + SQLite 持久索引”，默认支撑 1 亿条指纹上限，主要消耗磁盘而不是内存。

服务器会把所有去重后的弹幕追加保存到 `server/data/raw_messages.jsonl`。场次不再依赖单独复制一份完整弹幕，而是在全量日志上记录 `sliceStartSeq` / `sliceEndSeq` 切片；实时关键词统计只更新当前切片。需要离线处理某一轮时，可导出切片：

```bash
python3 tools/export_round_slice.py --data-dir server/data --round "第一轮" --out output/round-1.jsonl
```

## 三、发布 github.io 公开结果页

生产环境的 Token、Pages 与服务端发布配置统一见 [完整部署手册的 GitHub Pages 章节](docs/DEPLOYMENT.md#5-配置-github-pages-公开结果页)。

公开仓库：[PYXXXX/MangoTV_Danmaku](https://github.com/PYXXXX/MangoTV_Danmaku)

客户端结果页：[https://pyxxxx.github.io/MangoTV_Danmaku/](https://pyxxxx.github.io/MangoTV_Danmaku/)

仓库已启用 GitHub Pages，并由 [.github/workflows/pages.yml](.github/workflows/pages.yml) 自动部署 `site` 目录。运营端只发布聚合后的 `site/data/results.json`；推送完成后，Actions 自动更新公开页，不上传原始弹幕、昵称、服务端配置或去重数据库。

推荐的场次公开流程：

1. 在管理 WebUI 输入活动名与场次名后开始采集。
2. 点击“结束场次”，系统锁定 JSONL 切片，并把北京时间范围追加到场次名。
3. 运营人员检查票数与待审数量；需要语义清洗时先导出该场次切片。
4. 需要快速对外展示时点击“发布粗略结果”；数据来自实时切片关键词统计。
5. 需要精确结果时按 [Agent 清洗规范](docs/PRECISE_RESULT_AGENT.md) 完成清洗，上传 `precise_result.json` 或 `precise_result.xml`。服务端校验后立即发布。
6. GitHub Actions 部署成功后，公开客户端会在下一次轮询时显示新结果，并默认优先展示精确结果；访客仍可切换查看粗略结果。

### 配置运营端自动同步

扩展使用 GitHub Contents API 更新 `site/data/results.json`，更新后会自动触发 Pages 工作流。请创建一个 **fine-grained personal access token**：

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens。
2. Repository access 只选择本工具所在的**单个仓库**。
3. Repository permissions 只授予 **Contents: Read and write**。
4. 设置合理的过期时间并生成 token。
5. 打开扩展的“GitHub Pages 公开同步”，填写仓库所有者、仓库名、`main` 分支、结果路径和 token。
6. 建议同步间隔保持 `120` 秒，点击“保存配置并立即同步”。

采集中会按间隔提交一次聚合结果；点击“结束并保存本轮”或重命名场次时会立即提交。公共页面每 30 秒检查一次新部署结果。

> GitHub Pages 是静态托管，不是 WebSocket 服务。这个无后端方案属于“分钟级近实时”：延迟由同步间隔和 Actions 部署时间共同决定。若节目要求秒级刷新，需要另接公司内部 API、对象存储或实时数据库。

公共站点不依赖境外字体或第三方 CDN，以减少额外网络链路；但 `github.io` 在中国内地的可达性和速度不属于 GitHub 的稳定性承诺。正式大型直播建议准备公司自有域名/CDN镜像作为备用入口。

安全说明：token 只保存在本机 Chrome 扩展存储，不写入导出文件或公开仓库；GitHub 上仅保存候选人、轮次名称、票数、样本量和时间。正式运营建议使用独立机器人账号或 GitHub App，并定期轮换 token。

## 四、离线清洗 + Codex 语义理解

先复制并补充节目背景：

```bash
cp config/program_context.example.md config/program_context.md
```

执行本地清洗：

```bash
python3 tools/offline_clean.py ~/Downloads/mgtv-danmaku-xxx.jsonl \
  --context config/program_context.md \
  --out output
```

输出目录包含：

- `clean_messages.jsonl`：规范化后的完整消息，供审计，不应直接发给模型。
- `accepted.jsonl`：本地规则已明确判定的票。
- `review_batches/`：只含歧义弹幕的紧凑批次，不含昵称和时间，节省 token。
- `codex_prompt.md`：包含候选人、节目背景、判定口径和严格输出格式。
- `preliminary.json`：规则票数与待审规模。

然后在 Codex 中直接说：

```text
请严格按 output/codex_prompt.md 审核其中指定的 review_batches，生成 output/codex_decisions.jsonl。
```

不要让 Codex 重读原始 JSONL 或 `clean_messages.jsonl`。审核完成后合并：

```bash
python3 tools/merge_results.py output
```

最终得到：

- `output/final_result.json`：机器可读排名和审核完整性。
- `output/final_report.md`：可直接查看的票数表。
- `output/precise_result.json`：运营端可上传的精确结果 JSON。
- `output/precise_result.xml`：与 JSON 等价的精确结果 XML。

Agent 在开始审核前必须阅读 [docs/PRECISE_RESULT_AGENT.md](docs/PRECISE_RESULT_AGENT.md)。`offline_clean.py` 也会把该规范复制为输出目录内的 `AGENT_INSTRUCTIONS.md`，避免遗漏清洗与发布约束。

若 `preliminary.json` 的 `reviewMessages` 为 0，可以跳过 Codex，直接执行合并脚本。

## 五、计票边界

- 实时模式按**弹幕条数**计，不按昵称去重；这是“提到名字就计票”的直观实现。
- 服务器模式由于接口没有稳定消息 ID，按 `用户标识 + 昵称 + 内容` 去重；更适合防重复刷屏，但和 Chrome 扩展逐条 DOM 计数略有不同。去重上限默认 1 亿条，完整索引落 SQLite，内存只保留近期热指纹。
- 一条弹幕对同一艺人重复多次仍是 1 票，避免“张远张远张远”被算成 3 票。
- 离线规则自动放行单人、无否定、无比较的明确提及。
- 否定、淘汰语境、多人、比较问句、`陈老师` 这类泛称会进入 Codex。
- 没出现候选人或别名的弹幕不会交给 Codex；这既符合“提到名字才计票”，也能显著控制 token。
- 昵称不是稳定用户 ID，因此当前版本不宣称实现“每位观众只能投一次”。如果节目规则需要防刷，应接入内部用户 ID 或服务端消息 ID。

## 六、数据与稳定性

- 原始弹幕和昵称只保存在本机 Chrome 扩展存储及用户主动导出的文件中；启用 GitHub 同步后只上传聚合结果。
- 扩展只匹配 `https://www.mgtv.com/z/*`。
- Chrome 长直播存储已申请 `unlimitedStorage`；消息按 50 条分块，避免整场反复重写。
- 页面刷新会终止当前内容脚本。正式场次建议停止并导出后再刷新；若异常刷新，请新开一场采集，避免把页面重新加载的历史 80 条重复计入旧场次。
- 服务器模式不受页面刷新影响；如果网络断开或接口短暂异常，会按 `mgtv.reconnect_seconds` 自动重试。

## 七、测试

```bash
node --check extension/content.js
node --check extension/background.js
node --check extension/popup.js
node --check extension/dashboard.js
node --check site/app.js
node --check server/webui/app.js
python3 -m py_compile server/vote_server.py
python3 -m py_compile server/feishu_cards.py server/feishu_ws.py server/operator_auth.py
python3 -m py_compile tools/setup_feishu_bot.py tools/setup_operator_password.py
python3 -m unittest discover -s tests -v
```
