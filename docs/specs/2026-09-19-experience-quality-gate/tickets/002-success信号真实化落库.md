# 002 · success 位开始携带信息（tool_result 贯通到落库）

**Blocked by**: 001

## 目标

一轮里任一工具结果失败 ⇒ 这轮经验不得记为成功；无工具轮 ⇒ 落"无证据"而不是"成功"。
这是全批地基：`success` 恒真时，其余任何门槛都只是给噪声盖章。

## 涉及层

- [x] 逻辑层：`post_chat_pipeline.py:1612` 聚合改法（只统计 `type == "tool_result"`；
  语义取 `all` 而非 `any`；无结果记录时返回 `None`）
- [x] 逻辑层：同根因命中点一并收 —— `:3055`（规则臂字面量 `"success": True`）
- [x] 数据层：EKB 行 `success` 可为 0；无证据不得写成 1
- [x] 测试：001 的红基线转绿

## 命中点

- 正确写法同文件已存在，照抄口径：`post_chat_pipeline.py:2115`
  `tm.get("type", "") == "tool_result" and tm.get("success", False)`
- 落库参数：`:1648` `success=tool_success`；规则臂 `:3052-3057`

## 验收标准

- 001 基线转绿：含失败结果的轮 ⇒ 落库 `success=0`。
- 反向锁（防"一律记失败"蒙绿）：全成功轮必须仍记 `success=1`，且行数不因本票改变。
- 无工具轮不得记成功：该行须为"无证据"表示（D1：可入库、必须标出）。
- 临时库实测分布首次出现非全 1 —— 本批最低有效性证据。

## 净 LOC

预期接近 0：聚合表达式改写 + 一处字面量替换。

## 执行结果（已完成）

- 根因点：`post_chat_pipeline` 的 `any(tm.get("success", True) ...) if tool_messages else True`
  ——`tool_call` 记录根本没有 `success` 键，默认值 True 把"没测到"读成"没出问题"，
  且无工具轮次直接 `else True`。
- 修法：新增 `neurova/agent/turn_state.py:resolve_tool_outcome(records) -> Optional[bool]`
  三态判据（只看 `tool_result` 记录；无 result ⇒ None＝无证据），
  两条臂（EKB 写入、规则融合）同吃这一个判据。
- 落库：`success=bool(tool_success)`；`tool_success is None` 时 `tags=["unevidenced"]`
  ——D1 口径，可入库但必须带无证据标记，不砍量。
- 规则臂：`turn_outcome is None` 时不融合（原来无据照样投成功票）。
- 反例锁在 `test_success_signal_baseline.py`：只有 `tool_call` 记录 ⇒ 判无据；
  一条 `tool_result(success=False)` ⇒ 判 0；全 True ⇒ 判 1。
