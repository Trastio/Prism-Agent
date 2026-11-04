# 作废跑次登记（2026-11-02）

> 原因统一：模型侧 **402 Insufficient Balance**，agent 零 token 产出，回复为空、工具调用 0。
> 处置：保留原始文件作为事故证据，**不得作为基线、不得参与回归比较、不得引用其分数**。

| run_id | 规模 | 现象 | 自证状态 |
|---|---|---|---|
| eval-2026-11-02T05-58-23-241Z-r3 | 63 题 × 3 = 189 跑 | 147 跑次为「响应中断（20s 无事件）」+ 空回复；表观 avg 2.96、及格 65/189 | 报告 `summary.run_valid=true`（**未自证无效**，属已知缺陷） |
| eval-2026-11-02T08-09-07-655Z-r3 | 1 题 × 3 = 3 跑 | 3/3 空回复；退出码 2（轨迹覆盖率 0%，run-invalid 分支生效） | `summary.run_valid=false` |

## 复核依据

- 会话日志实锤：`stopReason: "error"`、`errorMessage: "402: Insufficient Balance"`
- 报告逐跑字段：`error` 非空、`tools=[]`、`reply_full=""`、`cost.tool_calls=0`
- 台账已标注：`eval/EVAL_STATUS.md` 2026-11-02 07:40 行已加「※作废」

## 后续防复发

- 方案 P1：runner 增加余额预检，402/401 直接退出，不进入批跑
- 建议（未实施）：runner 增加「空回复率 > 20% 则 summary.run_valid=false」自证闸，避免报告自称有效
