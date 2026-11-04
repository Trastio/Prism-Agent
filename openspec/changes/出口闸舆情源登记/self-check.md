# Self-check · 3.5 自查收敛（5 Gap 全修入设计）

- **G1 名称真值采集范围（关键缺口，explore 时漏了）**：tool_result hook `if (!event.toolName.startsWith('query_')) return` —— resolve_series 与 sentiment_* 的结果**从不进 prism-name-truth**。风云T7 案首轮真值集里根本没有"风云T7"，前缀放行无锚。修法：采集范围扩为 query_* + resolve_series + sentiment_*；**_meta as_of 校验保持仅 query_***（舆情/resolve 无此协议，套上会全部被 _warning 改写）；NAME_FIELDS 追加 `canonical_name`（resolve_series flat 对象）/`dim`（sentiment_dimension 行）/`event_tag`（事件行）/`platform`（帖子行，防"抖音/快手"误报）。
- **G2 sentiment_posts/events 非 uuid 参数**：模型自然写法是 `sentiment_posts:风云T7`（工具自身参数就是 vehicle_name）。规则：参数是 uuid 形态→精确查 id；否则按车系名查车辆存在。不再拒。
- **G3 _open_live 条件开**：无三维度引用时不开 autohome 连接（避免双连接常态开销）。
- **G4 collectNameTruth 加字段的影响面**：只增真值名（更宽松），grounding.test.ts 旧 8 case 的 fixture 无新字段，不回归；smoke:grounding 复跑确认。
- **G5 E2E 断言补一条**：sentiment 工具结果不得被 _warning 注入（G1 的回归探针）。

另确认：extractNameTokens 的 CJK 连续段正则（[一-龥]{2,}）证实"风云T7"→token"风云"——前缀放行放 verifyNames 循环开头是对的。
