# spec · 线 C 上游工具层（并行）

## 待办清单

1. C0（前置·运维）：验收前复查 8000/8001/8002/9200 监听 + /health needsRestart=False（explore 实测当前已就位）
2. C1：sentiment_events 路径 `/top-events/{vehicle_id}` → `/vehicles/{vehicle_id}/events`（router 相对路径，防 /api/dashboard 双前缀）；可选：施工期路径校验脚本（模板 ∈ dashboard.py 21 条路由）
3. C2：get_sales_detail schema 描述强化（series=车系名非 model_id）+ AUTOHOME_TOOL_MAP 注释对齐
4. C3：全部业务工具 execute 失败统一返回 `{status:'unavailable', tool, reason, fallback:'none'}`（HTTP 码进 reason）；台账抽取跳过该形态（与 gate.md 采集规则同批）

## 设计细节

- C3 与 M1 台账抽取**同批对齐**（失败形态变了，抽取规则同步）
- 不动上游服务部署（方案 §七.7）

## 验收标准

- N10：服务正常时舆情 6 工具全部可用；失败返回结构化 unavailable；轨迹 bash 占比显著降；E7 通过
