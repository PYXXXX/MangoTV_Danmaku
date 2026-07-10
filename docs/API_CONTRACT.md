# Live Ops Studio API 契约

本文档定义新版前端依赖的稳定 API。旧接口在迁移期保留，但新前端不应再依赖文本命令式接口完成核心操作。

## 约定

- 所有响应使用 JSON，除文件下载和 PNG 外。
- 时间字段使用 ISO 8601 UTC 字符串。
- 错误响应：

```json
{
  "error": "可给运营阅读的错误信息",
  "code": "OPTIONAL_MACHINE_CODE"
}
```

- 敏感字段永不回显：token、app_secret、cookie、device_code、user_code、密码、session。

## 聚合引导接口

### `GET /api/studio/bootstrap`

管理端首屏聚合状态，减少瀑布请求。

```json
{
  "generatedAt": "2026-07-07T09:00:00.000Z",
  "defaults": {
    "activityName": "歌手 2026",
    "publicResultsUrl": "https://pyxxxx.github.io/MangoTV_Danmaku/"
  },
  "activity": {},
  "monitor": {},
  "activeRound": {},
  "rounds": [],
  "recordings": [],
  "services": {},
  "permissions": {
    "operatorAuthenticated": true
  }
}
```

## 活动

### `GET /api/activities`

```json
{
  "items": [
    {
      "id": "1001668",
      "name": "歌手 2026",
      "url": "https://www.mgtv.com/z/1001668/5366.html",
      "status": "waiting",
      "monitorEnabled": true,
      "createdAt": "...",
      "updatedAt": "..."
    }
  ]
}
```

### `POST /api/activities`

请求：

```json
{
  "name": "歌手 2026",
  "url": "https://www.mgtv.com/z/1001668/5366.html",
  "monitorEnabled": true
}
```

### `PATCH /api/activities/{activity_id}`

部分更新活动信息。

### `DELETE /api/activities/{activity_id}?publish=1`

删除活动下已结束场次；若存在采集中场次，应返回 409。

## 活动监控与直播源

### `GET /api/activities/{activity_id}/monitor`

```json
{
  "enabled": true,
  "status": "waiting|checking|source_ready|running|error|disabled",
  "message": "等待开播",
  "lastCheckAt": "...",
  "lastError": "",
  "policy": {
    "autoDetectSource": true,
    "autoRecordVideo": true,
    "autoRecordDanmaku": true,
    "feishuNotify": true,
    "pollSeconds": 45,
    "preferredQuality": "auto"
  }
}
```

### `POST /api/activities/{activity_id}/monitor/start`

### `POST /api/activities/{activity_id}/monitor/stop`

### `POST /api/activities/{activity_id}/source/detect`

请求：

```json
{
  "quality": "auto",
  "persist": true
}
```

响应：

```json
{
  "ok": true,
  "activityId": "1001668",
  "pageUrl": "https://www.mgtv.com/z/1001668/5366.html",
  "cameraId": "5366",
  "roomId": "liveshow-5366",
  "sourceInputMode": "direct_camera",
  "quality": "1080P",
  "actualQuality": "1080P",
  "availableQualities": ["1080P", "720P"],
  "loginRequired": false,
  "vipRequired": false,
  "recordable": true,
  "streamUrlConfigured": true,
  "liveStatus": "live",
  "streamBeginTime": "2026-07-10 18:25:00",
  "streamEndTime": "2026-07-11 05:00:00",
  "message": "已解析直播源"
}
```

## 场次

### `GET /api/rounds?activityId=&status=&cursor=&limit=`

### `POST /api/rounds/start`

请求：

```json
{
  "activityId": "1001668",
  "activity": "歌手 2026",
  "name": "第 1 轮",
  "url": "https://www.mgtv.com/z/1001668/5366.html",
  "recordVideo": false,
  "collectDanmaku": true
}
```

### `PATCH /api/rounds/{round_id}`

请求：

```json
{
  "name": "选歌环节"
}
```

### `POST /api/rounds/{round_id}/end`

结束场次，可选自动发布粗略结果。

```json
{
  "publish": true
}
```

### `POST /api/rounds/{round_id}/publish`

```json
{
  "resultKind": "rough|precise"
}
```

### `DELETE /api/rounds/{round_id}?publish=1`

## 结果

### `GET /api/rounds/{round_id}/results`

```json
{
  "roundId": "round_1",
  "currentType": "rough",
  "rough": {
    "messageCount": 12486,
    "reviewCount": 12,
    "voteCounts": {}
  },
  "precise": null,
  "ranking": [
    {
      "candidateId": "c1",
      "name": "周深",
      "votes": 12486,
      "percent": 42.1,
      "trend": 6.3,
      "leader": true
    }
  ],
  "publishedAt": "..."
}
```

### `GET /api/rounds/{round_id}/result.png?result=rough`

PNG 文件。

### `POST /api/rounds/{round_id}/precise-result`

multipart 上传。

## 录制后处理

### `GET /api/recordings`

### `POST /api/recordings/start`

独立启动视频与弹幕录制；可与实时运营场次并行。

### `POST /api/recordings/{round_id}/stop`

停止独立录制。服务先把状态持久化为 `stopping`，确认 FFmpeg 进程组退出并完成视频封装后返回；自动切片在后台继续，不阻塞停止响应。该接口不会结束实时运营场次。

### `GET /api/recordings/{round_id}`

```json
{
  "roundId": "round_1",
  "status": "pending|recording|stopping|finished|failed|stop_failed|skipped|interrupted",
  "hasVideo": true,
  "videoUrl": "/api/rounds/round_1/recording/video",
  "durationSeconds": 7220.5,
  "fileSizeBytes": 123456789,
  "timelineOriginAt": "2026-07-10T11:27:19.000Z",
  "videoStartedAt": "2026-07-10T11:27:19.120Z",
  "danmakuStartedAt": "2026-07-10T11:27:19.180Z",
  "alignment": {
    "version": 1,
    "clock": "server_utc",
    "method": "wall_clock_capture",
    "videoStartOffsetSeconds": 0.12,
    "danmakuStartOffsetSeconds": 0.18,
    "danmakuPollingSeconds": 2
  },
  "markers": [],
  "clips": []
}
```

处理后的弹幕 JSONL 与原始弹幕 JSONL 都带 `captureOffsetSeconds`。片段导出以 `videoStartedAt` 为视频 0 秒映射弹幕时间；旧录制没有对齐元数据时兼容回退到 `startedAt`。

### `GET /api/recordings/{round_id}/timeline`

```json
{
  "durationSeconds": 7220.5,
  "danmakuDensity": [
    { "t": 0, "count": 12 },
    { "t": 30, "count": 42 }
  ],
  "markers": [],
  "clips": []
}
```

### `POST /api/recordings/{round_id}/markers`

### `PATCH /api/recordings/{round_id}/markers/{marker_id}`

### `DELETE /api/recordings/{round_id}/markers/{marker_id}`

### `POST /api/recordings/{round_id}/clips`

### `PATCH /api/recordings/{round_id}/clips/{clip_id}`

### `DELETE /api/recordings/{round_id}/clips/{clip_id}`

### `POST /api/recordings/{round_id}/clips/{clip_id}/analysis-round`

## 飞书

### `GET /api/feishu/status`

```json
{
  "enabled": true,
  "connectionMode": "websocket",
  "connected": true,
  "allowedOpenIdCount": 2,
  "allowedChatIdCount": 1,
  "lastPushAt": "...",
  "lastError": ""
}
```

### `POST /api/feishu/push-card`

同步当前工作台卡片。

### `POST /api/feishu/test-card`

发送测试卡片。

## 机器状态

### `GET /api/system/status`

机器状态页主接口。响应会尽量返回真实系统观测值；宿主机不暴露某项能力时返回 `available=false` 或空值，不伪造数据。

```json
{
  "ok": true,
  "generatedAt": "2026-07-07T09:00:00.000Z",
  "systemTime": "2026-07-07T17:00:00+08:00",
  "timezone": "Asia/Shanghai",
  "platform": "Linux-...",
  "python": "3.12.0",
  "host": {
    "hostname": "ops-studio-01",
    "paths": {
      "repoRoot": "/opt/MangoTV_Danmaku",
      "config": "/var/lib/mgtv-danmaku/config.json",
      "storage": "/var/lib/mgtv-danmaku/data",
      "recordings": "/var/lib/mgtv-danmaku/data/recordings"
    },
    "cpu": {
      "model": "Intel(R) Xeon(R)",
      "architecture": "x86_64",
      "temperature": {
        "available": false,
        "celsius": null,
        "error": "未发现可读取的 CPU 温度传感器"
      }
    }
  },
  "backup": {
    "available": true,
    "latestAt": "2026-07-07T08:59:00.000Z",
    "name": "config.json.bak",
    "sizeBytes": 2048,
    "count": 1
  },
  "startedAt": "2026-07-07T08:00:00.000Z",
  "uptimeSeconds": 3600,
  "process": {
    "pid": 1234,
    "name": "mgtv-danmaku",
    "rssBytes": 104857600
  },
  "cpu": {
    "count": 2,
    "loadPercent": 38.0,
    "loadAverage": [0.76, 0.62, 0.51],
    "model": "Intel(R) Xeon(R)",
    "architecture": "x86_64",
    "temperatureAvailable": false,
    "temperatureCelsius": null
  },
  "memory": {
    "totalBytes": 4294967296,
    "availableBytes": 2147483648,
    "usedBytes": 2147483648,
    "processRssBytes": 104857600
  },
  "network": {
    "available": true,
    "rxBytes": 123456789,
    "txBytes": 987654321
  },
  "disk": {
    "data": {"ok": true, "path": "/var/lib/mgtv-danmaku/data", "totalBytes": 1, "usedBytes": 1, "freeBytes": 1},
    "recordings": {"ok": true, "path": "/var/lib/mgtv-danmaku/data/recordings", "totalBytes": 1, "usedBytes": 1, "freeBytes": 1}
  },
  "services": {
    "collector": {"status": "running", "activeRoundId": "round_1"},
    "recorder": {"status": "recording", "activeCount": 1, "enabled": true},
    "feishu": {"status": "connected"},
    "github": {"status": "enabled"},
    "updater": {"status": "idle"},
    "monitor": {"status": "running", "enabled": true, "taskRunning": true},
    "recordingSource": {"configured": true, "quality": "1080P", "availableQualities": ["1080P", "720P"], "detectedAt": "..."}
  },
  "health": {
    "status": "ok",
    "restartRequired": false,
    "restartFields": [],
    "recentErrorCount": 0
  }
}
```

### `GET /api/system/host`

返回主机与路径详情，供机器状态页、诊断面板和运维排查使用。字段与 `status.host` 基本一致，并额外包含 `backup`。

### `GET /api/system/metrics?window=15m`

```json
{
  "window": "15m",
  "points": [
    {
      "time": "...",
      "cpuPercent": 38.0,
      "memoryPercent": 52.5,
      "rxBytesPerSecond": 312000,
      "txBytesPerSecond": 148000,
      "danmakuPerSecond": 423
    }
  ]
}
```

## 系统日志

### `GET /api/system/logs`

查询参数：

- `level`
- `source`
- `q`
- `from`
- `to`
- `cursor`
- `limit`

响应：

```json
{
  "ok": true,
  "generatedAt": "2026-07-07T09:00:00.000Z",
  "items": [
    {
      "id": "log_9f3f4e2b7c6a",
      "time": "2026-07-07T07:27:45.001Z",
      "level": "ERROR",
      "source": "recorder",
      "sourceLabel": "录制进程",
      "summary": "ffmpeg 退出码异常",
      "detail": "ffmpeg exited with code 1",
      "roundId": "round_20260707_01",
      "host": "ops-studio-01",
      "errorMessage": "ffmpeg exited with code 1",
      "remediation": [
        "查看同一来源前后 5 条日志，确认异常发生前后的状态变化。",
        "检查录制目录剩余空间与写入权限。"
      ]
    }
  ],
  "events": [],
  "total": 1248,
  "cursor": 0,
  "limit": 20,
  "nextCursor": "",
  "previousCursor": "",
  "sources": ["recorder"],
  "availableSources": ["service", "monitor", "collector", "recorder", "feishu", "github", "updater"],
  "sourceLabels": {
    "recorder": "录制进程"
  },
  "levels": ["ERROR"],
  "availableLevels": ["INFO", "WARN", "ERROR"],
  "levelCounts": {"ERROR": 1},
  "sourceCounts": {"recorder": 1},
  "timeline": [
    {
      "id": "log_9f3f4e2b7c6a",
      "time": "2026-07-07T07:27:45.001Z",
      "level": "ERROR",
      "source": "recorder",
      "sourceLabel": "录制进程",
      "summary": "ffmpeg 退出码异常",
      "roundId": "round_20260707_01"
    }
  ]
}
```

### `GET /api/system/logs/export`

导出当前筛选条件下的 JSON 日志文件。

### `POST /api/system/logs/summary`

请求体与日志查询参数一致：

```json
{
  "level": "ERROR",
  "source": "recorder",
  "q": "ffmpeg",
  "from": "2026-07-07T07:00:00.000Z",
  "to": "2026-07-07T08:00:00.000Z"
}
```

响应：

```json
{
  "ok": true,
  "generatedAt": "2026-07-07T09:00:00.000Z",
  "total": 1,
  "levelCounts": {"ERROR": 1},
  "sourceCounts": {"recorder": 1},
  "latestError": {},
  "summary": "筛选范围内共有 1 条日志；ERROR 1 条，WARN 0 条，INFO 0 条。",
  "suggestions": ["先按来源过滤同一模块，查看错误前后 5 条事件。"]
}
```

## 配置

### `POST /api/settings/diff`

传入拟保存配置，返回影响分析。

```json
{
  "hotReload": ["mgtv.poll_seconds", "feishu.allowed_open_ids"],
  "nextRound": ["mgtv.camera_id", "recording.preferred_quality"],
  "restartRequired": ["listen.port"],
  "warnings": [],
  "errors": []
}
```

### `POST /api/settings/validate`

只校验不保存。

### `POST /api/settings/apply`

保存并应用。
