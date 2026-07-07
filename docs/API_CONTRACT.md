# Live Ops Studio API 契约草案

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
      "url": "https://www.mgtv.com/z/1001668.html",
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
  "url": "https://www.mgtv.com/z/1001668.html",
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
  "pageUrl": "https://www.mgtv.com/z/1001668.html",
  "cameraId": "5366",
  "roomId": "liveshow-5366",
  "quality": "1080P",
  "actualQuality": "1080P",
  "availableQualities": ["1080P", "720P"],
  "loginRequired": false,
  "vipRequired": false,
  "recordable": true,
  "streamConfigured": true,
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
  "url": "https://www.mgtv.com/z/1001668.html",
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

### `GET /api/recordings/{round_id}`

```json
{
  "roundId": "round_1",
  "status": "recording|finished|failed|skipped|interrupted",
  "hasVideo": true,
  "videoUrl": "/api/recordings/round_1/video",
  "durationSeconds": 7220.5,
  "fileSizeBytes": 123456789,
  "markers": [],
  "clips": []
}
```

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

保留当前接口，字段逐步补齐。

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

### `GET /api/system/services`

### `GET /api/system/alerts`

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
  "items": [],
  "nextCursor": "",
  "sources": ["WebUI", "录制进程"],
  "levels": ["INFO", "WARN", "ERROR"]
}
```

### `GET /api/system/logs/{log_id}`

### `GET /api/system/logs/export`

### `POST /api/system/logs/summary`

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
