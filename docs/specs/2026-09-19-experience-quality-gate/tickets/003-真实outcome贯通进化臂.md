# 003 · 真实成败不再被关键词分类覆盖

**Blocked by**: 001

## 目标

调用方已经算出来的 `success` 必须走进经验语义；`classify_outcome` 的关键词只配做
"有成败之后的细分"，不得在无命中时把未知判成成功。

## 涉及层

- [x] 逻辑层：`experience_feedback.process_experience` 增 `outcome: Optional[str] = None`
  （现签名 `:243-246` 无此参数）
- [x] 逻辑层：`closed_loop.py:506-510` 把 `success` 传下去（当前算出 `outcome` 却丢弃）
- [x] 逻辑层：`experience_feedback.py:164` 的 `return "success"  # 默认为成功`
  改为返回"无证据"；关键词仅在 `outcome is None` 时兜底
- [x] 测试：单元 + 经 001 探针的贯通断言

## 命中点

- `process_experience` 内部 `:261` `outcome = self.classify_outcome(experience_text)`
- 关键词表 `:30-31`、计数 `:151-153`
- 下游消费：`create_task_tool_association`（`:275-279`），其 `success_rate`
  正是结晶门槛输入

## 验收标准

- 传 `success=False` 且经验文本含成功关键词 ⇒ `failure_count` 增加、`success_count` 不变
  （当前必红）。
- 关键词零命中 ⇒ 落"无证据"，不得抬高 `success_rate`。
- 反向锁：显式 `outcome=None` 时关键词兜底仍生效（不得把老行为一刀砍死）。

## 净 LOC

预期 +5 以内（新参数 + 一处分支），抵掉 `:163-164` 的默认成功分支。

## 执行结果（已完成）

- `closed_loop.on_experience_recorded`：原来把真实 `success` 丢弃、改由关键词分类
  决定 outcome（真实证据被自述覆盖）。现在
  `objective = None if success is None else ("success" if success else "failure")`，
  无票据时一律 None（无证据），不再代判。
- `experience_feedback.classify_outcome` 返回类型改 `Optional[str]`：关键词零命中时
  原实现 `return "success"`，现返回 None——`success_rate` 是结晶入库门槛的唯一输入，
  "没测到"被读成"没出问题"会让门槛退化成盖章机。
- `process_experience(..., outcome: Optional[str] = None)` 贯通下游。
- 旧契约测试按新语义重写（不删）：见 `tests/unit/evolution/test_experience_feedback.py`
  相关用例与本批 `tests/unit/evolution/experience/test_outcome_propagation.py`。
