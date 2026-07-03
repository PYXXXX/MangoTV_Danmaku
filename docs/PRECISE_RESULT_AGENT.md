# 精确结果清洗与语义审核规范

本文是执行精确结果清洗任务的 Agent 的强制规范。目标是把某一场次的完整 JSONL 切片转换为可审计、可重复生成、可由运营端校验上传的精确结果，同时尽量节省模型 token。

## 1. 输入与数据边界

- 输入必须是运营端导出的单场次 JSONL 切片，首行为 `type=meta`，后续为 `type=message`。
- 只能处理该切片内的弹幕，不能把其他场次、社交平台数据或常识票数混入结果。
- 候选人 ID、正式姓名和别名以 meta 中的 `candidates` 为唯一依据。
- 节目背景只用于理解语义，不能用来补造弹幕中没有表达的支持关系。
- 昵称不是可靠用户 ID。除非节目方另行提供稳定用户标识和去重规则，否则不执行“每人一票”推断。

## 2. 固定流水线

1. 运行 `tools/offline_clean.py`。该步骤完成 Unicode 规范化、空白清理、候选人匹配和规则分流。
2. 不要把原始 JSONL 或 `clean_messages.jsonl` 整体发送给模型。
3. 只读取 `review_batches/batch-*.jsonl` 和生成的 `codex_prompt.md`，逐条输出 `codex_decisions.jsonl`。
4. 运行 `tools/merge_results.py`，生成 `precise_result.json` 与 `precise_result.xml`。
5. 只有 `unresolvedReviewMessages=0` 且 `invalidDecisionLines=0` 的文件可以上传发布。

## 3. 文本清洗要求

- 使用 NFKC 统一全角/半角字符，移除零宽字符，合并连续空白。
- 保留否定词、比较词、问号、引用关系和人名附近的语气信息；这些内容影响语义，不能删除。
- 重复标点可以压缩，但不能把否定、反问或候选人名字改写掉。
- 空文本丢弃；未命中任何候选人或别名的弹幕不计票，也不交给模型。
- 单条弹幕对同一候选人最多计 1 票。
- 不得根据昵称、头像、发布时间或热度推断候选人。

## 4. 语义计票要求

- 明确支持、投票、希望留下，或节目口径明确规定的正向提及：计该候选人 1 票。
- “不投、别选、不支持、淘汰、出局”等否定或排斥表达：对应候选人不计票。
- 比较、提问、罗列选项但没有明确选择：不计票。
- 反讽、转述他人观点、歌词/标题引用、同名歧义：无法确认时不计票，原因写 `unclear`。
- 一条弹幕可以给多人计票，但每个人都必须分别满足明确支持条件。
- 泛称别名（如“老师”“哥”“姐”）只有在本场上下文能唯一指向候选人时才计票；否则不计票。
- 禁止为了提高覆盖率而猜测；精确结果优先保证可解释性。

## 5. Agent 输出协议

每条待审输入字段为：`i` 记录号、`t` 文本、`m` 本地命中的候选人 ID、`q` 待审原因。

`codex_decisions.jsonl` 每行只能包含一个 JSON 对象：

```json
{"i":12,"c":["c1"],"r":"support"}
```

- `i` 必须原样返回且每个待审记录只出现一次。
- `c` 只能包含 meta 中存在的候选人 ID；不计票时必须是空数组。
- `r` 只能使用：`support`、`reject`、`comparison`、`unclear`、`alias_error`。
- 不要输出 Markdown、解释段落、代码围栏或额外字段。

## 6. 可上传精确结果格式

运营端接受 UTF-8 `.json` 或 `.xml`，文件不超过 2 MB。推荐直接使用合并工具生成的文件，不要手工改票。

JSON 顶层字段固定为：

```json
{
  "schemaVersion": 1,
  "resultType": "precise",
  "sessionId": "场次 ID",
  "activity": "活动名",
  "sessionName": "含北京时间切片范围的场次名",
  "generatedAt": "UTC ISO-8601 时间",
  "counts": [
    {"candidateId": "c1", "name": "候选人正式姓名", "votes": 123}
  ],
  "audit": {
    "inputMessages": 1000,
    "cleanMessages": 998,
    "ruleAcceptedMessages": 600,
    "semanticReviewedMessages": 20,
    "unresolvedReviewMessages": 0,
    "invalidDecisionLines": 0
  }
}
```

XML 使用 `preciseResult/session/counts/candidate/audit` 结构；属性与 JSON 字段一一对应，以 `tools/merge_results.py` 的输出为准。

## 7. 发布前自检

- `sessionId` 和 `activity` 与运营端所选场次完全一致。
- `audit.inputMessages` 等于该场次保存的弹幕样本数。
- `counts` 恰好包含该场全部候选人，ID 和姓名匹配，票数均为非负整数。
- 无遗漏审核、无重复记录号、无未知候选人、无无效决策行。
- 不在精确结果中包含昵称、原始弹幕、密钥、直播接口响应或其他个人信息。
- 保留工具生成的中间文件用于内部审计，但只能公开上传聚合结果。
