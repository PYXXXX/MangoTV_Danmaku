# Live Ops Studio 重构归档

本文档记录 `codex/live-ops-studio-refactor` 分支的重构目标与落地状态。该分支已于 PR #5 合入 `main`，项目已从“弹幕投票统计”升级为“直播运营工作台”：活动监控、直播录制、弹幕采集、后处理分析、飞书协同、公开发布、机器监控和日志排障的一体化系统。

## 当前状态

- 管理端五个页面已落地：活动监控、运营工作区、系统配置、机器状态、系统日志。
- 前端已迁移到 `frontend/` 的 TypeScript + React + Vite + Tailwind CSS v4 工程。
- 后端已补齐新版 Studio 使用的结构化 API，并保留旧 WebUI 与旧接口兼容。
- 飞书 Bot 已对齐新版状态模型，继续采用卡片交互。
- 公开结果页继续通过 GitHub Pages 发布聚合结果，原始弹幕和昵称不公开。
- 验证命令：`python -m py_compile server/vote_server.py`、`npm --prefix frontend run typecheck`、`npm --prefix frontend run build`、`.venv/bin/python -m unittest discover -s tests -v`。

## 目标

1. 管理端与公开页完整对齐设计预览图的信息架构和交互模型。
2. 前端从原生 HTML/CSS/JS 迁移到可维护的 TypeScript + React 工程。
3. 后端从命令式接口逐步迁移到 typed API，保留旧接口兼容。
4. 数据模型引入活动、场次、录制、日志、指标、发布历史等一等实体。
5. 飞书 Bot 复用同一套后端状态模型，坚持卡片交互。

## 页面与功能边界

### 1. 活动监控

- 活动名称、官方活动页或直播 URL 配置。
- 自动识别 activity_id / room_id / camera_id。
- 开播监控。
- 自动检测直播源与清晰度。
- 自动录制视频、自动录制弹幕。
- 飞书通知与异常通知。
- 最近事件与当前状态。

### 2. 运营工作区

- 当前直播状态瀑布流：活动识别、直播源、录制、弹幕采集、清晰度。
- 实时运营：开始新一轮、结束并发布粗略结果、重命名、删除、导出。
- 场次表：状态、时间范围、弹幕数、结果类型、操作。
- 飞书协同：卡片预览、同步卡片、复制公开链接、发布公开页。
- 录制后处理：视频回看、时间轴、标记、切片、生成分析场次。
- 精确结果上传与发布。

### 3. 系统配置

- 连接与账号：芒果 TV 扫码登录、飞书 Bot、GitHub 发布。
- 采集与录制：弹幕接口、去重参数、录屏参数、直播源自动检测。
- 安全、存储与更新：运营密码、存储目录、监听端口、程序升级。
- 本次修改影响：立即热重载、下一场生效、需要安全重启。

### 4. 机器状态

- 系统时间、服务运行时长、进程、健康状态。
- CPU、内存、网络、磁盘。
- 服务运行状态：采集器、录制、飞书、GitHub、更新器、监控器。
- 最近告警。
- 15 分钟趋势：CPU、内存、网络、弹幕速率。

### 5. 系统日志

- 服务端分页、搜索、级别过滤、来源过滤、时间范围。
- 日志详情、命令/错误信息、建议排障。
- 事件时间线。
- 导出日志与生成排障摘要。
- 实时跟随。

### 6. 公开结果页

- 活动标题、当前场次、粗略/精确结果切换。
- 当前领先者卡。
- 排名表、占比、趋势。
- 场次时间线。
- 导出 PNG、复制链接、下载 JSON。
- 数据来源与免责声明。
- 最近发布记录。

## 前端技术栈

- TypeScript
- React
- Vite
- Tailwind CSS v4
- Radix UI primitives
- TanStack Query
- Zustand
- Apache ECharts
- Motion
- Phosphor Icons

前端代码放在 `frontend/`。构建输出：

- 管理端：`frontend/dist/admin`
- 公开页：`frontend/dist/public`

后端优先服务构建产物；构建产物不存在时回退到旧 `server/webui`，便于分阶段迁移。

## 美术资源

需要用 image2 生成或人工绘制：

1. `stage-hero.webp`：公开结果页舞台光束背景，2400×900。
2. `vote-ring.webp`：金色投票光环/声波纹，1600×600，透明或深色背景。
3. `mic-medal.webp`：金色麦克风奖章，512×512。
4. `video-placeholder.webp`：录制播放器空状态，1280×720。
5. `empty-state.webp`：暂无数据空状态，800×600。
6. `brand-mark.svg`：直播运营工作台品牌标识。

不使用 AI 生成真实艺人头像。候选人头像应来自授权素材或运营上传。

## 后端重构阶段归档

### Phase 1：契约和兼容层（已完成）

- 新增 typed API 文档。
- 保留旧 `/api/results.json`、`/api/command`、`/api/settings`。
- 增加新版聚合接口，减少前端多接口拼状态。

### Phase 2：活动与场次实体（已完成）

- 引入 activity store。
- 场次操作从文本命令迁移到 typed endpoint。
- 删除、发布、重命名全部结构化。

### Phase 3：录制后处理（已完成）

- markers/clips 增删改查。
- 录制时间轴。
- 弹幕密度序列。
- 片段分析任务状态。

### Phase 4：系统观测（已完成）

- 周期采集系统指标。
- 日志分页过滤。
- 告警和事件时间线。

### Phase 5：飞书统一状态模型（已完成）

- 飞书卡片读取同一套 activity/round/recording/status API。
- 卡片 action 不再直接散落在旧控制逻辑中。

## 迁移策略归档

1. 新前端和旧 WebUI 当前并存。
2. 新前端构建产物存在时，`/`、`/admin`、`/studio` 服务新前端。
3. 旧版 WebUI 保留在 `/legacy` 作为临时备用入口。
4. 旧接口继续保留，飞书、公开页和测试均已覆盖新版核心路径。
5. 后续如要删除旧静态 WebUI，应先确认生产环境无 `/legacy` 依赖。

## 验收标准

- `npm --prefix frontend run build` 通过。
- `npm --prefix frontend run typecheck` 通过。
- Python 全量测试通过。
- 管理端五页和公开页均可打开。
- 公开页能独立部署到 GitHub Pages。
- 核心操作具备加载态、错误态、空状态和确认态。
