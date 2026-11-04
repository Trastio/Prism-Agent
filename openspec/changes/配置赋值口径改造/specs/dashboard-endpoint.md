# spec · 端点与配置看板前端（配置赋值口径改造）

> 归档后补录（2026-10-13）：按施工实际执行的契约整理（含 Step8 修复）。对应 design.md D3/D4/D5，任务 T2.1-T2.4。

## 待办清单（已完成）

- [x] GET|POST /dash/config/compare-valued 端点
- [x] 前端切换：差价 JS 删净、改调后端、手填价随请求传后端
- [x] 旧链路收敛：fold_prices 删除（墓碑注释保留）、/config trim 视图 raw 行结构保留
- [x] hint 五规则 + 三态语义改"差价表兜底"

## 端点契约

```
GET  /dash/config/compare-valued?sel=mid:spec&sel=mid:spec   （2-6 个，第 1 个=基准列）
POST 同路径，body {"manual_prices": {param: 元}}              （手填覆盖，内存态不落库）
```

- 进：get_config_snapshot（缺快照→error 信封）→ spec_compare_horizontal 同源取数 → load_pricing_table → compute_value_diff → get_trims（活接口，try/except：失败 guide_prices=None，**逐项差价不受阻**）
- 出：`{**hc, diff:{columns/items/missing_rules/blocked/config_adv/flat_adv/flat_adv_reason/legacy:false}, guide_prices, as_of:{pricing_table, snapshots_fetched_at}}`
- 防线（Step8 P0-1）：manual_prices 经 float()+`>=0`+**isfinite** 三道校验，非法丢弃
- 拉平指导价优势：2 列 + 未 blocked + **config_adv 非 None**（审查 P1-1：不可用≠0）+ 双方指导价齐 → `round(config_adv + (基准指导价−对方指导价)×10000, 2)`；否则 flat_adv=None+reason

## 前端契约（dash_config.html §02）

- 首次渲染：renderHorizontalCompare(data) 接整页数据，**顶部清空 _manualPrices**（新对比对象不继承手填——审查 P2-5）
- 差价 tfoot：renderDiffFoot 只渲染后端 diff.columns，**前端零计算**（原 _computeDiffCells/_refreshFooter 已删，墓碑注释在）
- 手填改价：setRowPrice → refreshDiffFromServer → postCompareValued（POST 带 _manualPrices）→ 只刷 tfoot+摘要条
- fetch 守卫：`!r.ok || j.error` 双拒（error 信封走 200——审查 P2-6）
- 三态样式：绿=手填覆盖 / 蓝=差价表兜底（unit_price 非空）/ 灰=未定价或档位差价项；hint 五规则=①presence差×单价 ②数值差×单价 ③文本档位差双方落档相减 ④缺采不计价 ⑤缺规则拒绝汇总并列出

## 旧链路收敛

- fold_prices 函数删除（dashboard_data.py），/config trim= 视图保留 compare_trims raw 行结构（模板只消费 cfg_failed 守卫；totals/pair_diffs/guide_diff 本就零消费，guide_diff+_diff_vs_min 死代码一并清除——Step6）
- concept_config.py 的 _find_param/_extract_value/_concept_price_for_param 保留（spec_compare_horizontal 仍在用）；score_concept 保持归档无消费者

## 验收标准（已在 Step9 复核）

1. TestClient：真实配对 200 出逐项+合计；manual POST 覆盖生效；get_trims 失败 monkeypatch → 200 降级；缺快照/非法 sel 错误信封；Infinity 手填 → 200 正常出数
2. 活页面四检查：新 hint 在/新函数在/旧 JS 无/renderDiffFoot 在
3. 浏览器人工走查手填交互——**留用户，非阻塞声明项**

## 依赖

上游：valuation-engine spec；get_trims（活接口+TTL 缓存）。
