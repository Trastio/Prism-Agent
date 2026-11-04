# 硬编码清理 · Step 3.5 自查收敛

> 2026-10-06
> 对自己的 design.md 做自查：任务依赖完整 / 验收可验 / 技术前置交代 / 无悬空

---

## Gap 1（必修）· B 节 series_id 来源未交代 /identity/resolve 如何调

**问题**：design 说"OverviewBoard 加 useQuery /identity/resolve"，但没说 series 为空时该 useQuery 怎么处理（enabled: !!series），也没说 resolve 返回 series_id 后如何传给 CLAIM 卡。

**改法**：design B 节补：
- OverviewBoard 加 `useQuery({ queryKey: ['identity', series], enabled: !!series, queryFn: () => fetch(`/identity/resolve?series_key=${encodeURIComponent(series)}`).then(r=>r.json()) })`
- CLAIM 卡 series_id 从该 useQuery 结果取（`idData?.series_id`）
- series 空 → useQuery 不发 → CLAIM 卡空态

## Gap 2（必修）· Z1 model_id 来源未交代

**问题**：design Z1 说"从 useQuery 结果取 model_id"，但 ReviewsBoard 的 useQuery 返回的是 mv_reviews_dim 行（字段 model_id/series_name/tag_category 等）。需确认 model_id 在 rows[0] 里。

**改法**：Z1 改 `src: \`review_tags:model_id=${rows[0]?.model_id ?? '未知'}/tag_category=${r.tag_category}\``（从 rows 第一行取 model_id，兜底"未知"）。

## Gap 3（必修）· D 节 extension setActiveTools([]) 位置未明确

**问题**：design 说 `if (!seriesKey) { pi.setActiveTools([]); return ... }`，但没说插在 before_agent_start 哪一行（在解析 seriesKey 之后，在 fetch /identity/resolve 之前）。

**改法**：D 节补：在 `index.ts:572` seriesKey 解析后、`index.ts:595` if (seriesKey) 之前，加：
```ts
if (!seriesKey) {
  try { pi.setActiveTools([]); } catch {}
  return { systemPrompt: '对象未确认，请先选择车系（红线#7 fail-closed）。不要进行分析。' };
}
```

## Gap 4（小修）· F 节最近车系 localStorage key 命名

**问题**：design 说 `prism_recent_series`，但没说存什么格式（字符串数组 vs 对象）。

**改法**：F 节补：`localStorage.setItem('prism_recent_series', JSON.stringify(arr))`，arr 是字符串数组（车系名），读取 `JSON.parse(localStorage.getItem('prism_recent_series') || '[]')`。

## Gap 5（小修）· 验收 0 的 Windows 命令

**问题**：design 验收 0 用 `find`（Unix），本机 Windows。

**改法**：改 `Get-ChildItem -Path prism-web/src -Recurse -Filter *.js` 或 `ls prism-web/src -Recurse -Filter *.js`。

---

## 自查结论

- 5 Gap 全修（3 必修 + 2 小修）
- 任务依赖完整（B/Z1/D/E/F 均有数据来源交代）
- 验收可验
- 技术前置交代（series_id 来源 / model_id 来源 / setActiveTools 位置）
- 无悬空

**可进 Step5 subagent-driven-development**。
