# 芒果直播弹幕接口排查记录

排查对象：https://www.mgtv.com/z/1001668/5366.html

## 结论

当前 PC Web 客户端用于热聊历史的接口是：

    GET https://lb.bz.mgtv.com/get_history?room_id=liveshow-{cameraId}

当前示例页面的 cameraId 是 5366，因此 room_id 是：

    liveshow-5366

前端包中对应调用位于 webpack module 339，函数导出名为 f，代码逻辑等价于：

    const params = { room_id: flag + '-' + key };
    return axios.get('https://lb.bz.mgtv.com/get_history', { params }).then(res => res.data);

在当前前端代码里，没有看到 cursor、last_id、since、page、pageSize 等增量参数参与该调用。

## 返回结构

接口返回示例结构：

    {
      "code": 0,
      "msg": "success",
      "data": [
        {
          "t": 1,
          "u": "c80fdf9ab50b5394bbeff778a4a5620d",
          "n": "友好的Ω肉夹馍",
          "c": "拜拜",
          "r": 0,
          "g": 1,
          "l": 2,
          "a": "https://avatar.hitv.com/...",
          "e": "",
          "af": "",
          "ft": 0
        }
      ]
    }

字段观察：

- u：用户标识。
- n：昵称。
- c：弹幕正文。
- t：消息类型。
- a：头像。
- r/g/l/ft/...：展示或身份相关字段。

目前样例中未看到稳定的 messageId、msg_id 或 mid 字段。

## 其他相关接口

同一模块还包含：

- https://lb.bz.mgtv.com/live/sendmsg：发送弹幕。
- https://comment.mgtv.com/v4/comment/topComment：评论区置顶评论。
- https://comment.mgtv.com/v4/comment/getCommentList：评论区列表。
- https://comment.mgtv.com/v4/comment/getReplyList：评论回复。
- https://lb.bz.mgtv.com/get_materials：直播素材，不是弹幕增量。

mgtv-live-kernel 包主要处理直播视频播放、HLS/FLV、上报和 P2P，没有发现热聊弹幕增量游标接口。

## 试探参数

已用这些参数做过行为试探：

- cursor=0
- last_id=0
- since=0
- page=1&pageSize=20
- _support=10000

目前未观察到前端使用这些参数，也未观察到接口返回游标字段。接口更像“当前房间最近热聊快照”，不是完整历史回放或增量拉取。

## 当前服务端策略

由于暂未发现稳定消息 ID 或游标，服务器版采用：

    用户标识 + 昵称 + 内容

生成去重指纹，并通过“内存热 LRU + SQLite 持久索引”控制内存。默认配置下，内存热缓存 20 万条，SQLite 去重索引上限 1 亿条。若未来开发确认接口可返回 messageId 或支持 cursor/since_id，服务端已预留自动优先使用常见 ID 字段：

- messageId
- message_id
- msg_id
- mid
- id
