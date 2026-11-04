# Design · 出口闸舆情源登记

## 数据流（改后）

```
模型 submit_conclusion(supported_by=["sentiment_overview:风云T7", ...])
  └─ extension execute (L384)
      └─ POST /verify/claim  { supported_by }
          └─ prism-api main.py verify_claim()
              ├─ 三维度分支（现状不动，_open_live → autohome.db）
              └─ 新增 sentiment_* 分支 → _open_sentiment()（只读 vehicle_sentiment.db）
```

## T1 · /verify/claim 舆情分支

```python
SENTIMENT_DB = os.environ.get('PRISM_SENTIMENT_DB',
    str(Path(__file__).parent.parent / 'prism-sentiment' / 'data' / 'vehicle_sentiment.db'))

def _open_sentiment():
    # 只读连接；文件缺失 raise（调用方 fail-closed）
    return sqlite3.connect(f'file:{SENTIMENT_DB}?mode=ro', uri=True)
```

分支逻辑（table 名匹配后）：

| 引用 | 校验 |
|---|---|
| `sentiment_overview:{名}` / `sentiment_trend:{名}` / `sentiment_competitive:{名}` | vehicles 存在：`name = ?`（去空格）→ 兜底 `name LIKE '%'||?||'%'`（LIKE 转义） |
| `sentiment_dimension:{名}/{维度}` | 车辆存在 + `analyzed_posts.dim_sentiment LIKE '%"维度"%'`（该车辆 LIMIT 1） |
| `sentiment_posts:{uuid}` | `raw_posts.id = ?` |
| `sentiment_events:{uuid}` | `event_groups.id = ?`；`sentiment_events:{车系名}`（非 uuid 形态）→ 车辆存在 |
| `sentiment_board:{名}/...` | 车辆存在（宽容分支：风云T7 案里模型自造的格式） |

- uuid 识别：`len==36 and 8-4-4-4-12 连字符形态`（不做严格 hex 校验，够用）
- **fail-closed 边界**：sentiment DB 打不开（FileNotFoundError/OperationalError）→ 该 sentiment_* 引用记 failure `舆情库不可达`；三维度分支不受影响。连接每请求开关（与 _open_live 同生命周期）。
- 维度 LIKE 需对 `%/_` 转义（与 identity_resolve 的 P2-7 同款转义）。

## T2 · extension 描述文案（8 处）

- submit_conclusion description（L359）追加：``sentiment_overview:风云T7``（舆情车系名）、``sentiment_posts:<帖uuid>``、``sentiment_dimension:风云T7/续航``
- 拒绝提示（L462-463）追加同款一句
- 6 个舆情工具 description 各追加一行：`行 ID 引用格式：sentiment_overview:{车系名}`（按工具对应格式）

## T3 · verifyNames 前缀放行（grounding.ts）

在 `for (const token of modelTokens)` 循环开头、`isNameInTruth` 之后加：

```ts
// R1 最小修：纯 CJK 前缀放行——"风云"是"风云T7"的前缀且余部非 CJK → 合法简称
if (/^[一-鿿]{2,}$/.test(token)) {
  let prefixOk = false;
  for (const t of truthSet) {
    if (t.startsWith(token) && !/^[一-鿿]/.test(t.slice(token.length))) { prefixOk = true; break; }
  }
  if (prefixOk) continue;
}
```

- 纯 CJK ≥2 字 + 真值名以它开头 + 余部首字符非 CJK（T7/E5/7X/03…）→ 放行
- 8 条旧测试不受影响（无一是此形态）；新测试 case：`verifyNames("风云T7", {"风云T7","空间"})` 与 `verifyNames("风云 续航", {"风云T7","空间","续航"})` pass；反向 `verifyNames("蔚来Z9", {"腾势Z9"})` 仍 fail（蔚来不是任何真值前缀，走原 closest 逻辑）

## T4 · 前端文案（ChatView.tsx:258-260）

```
验证器已自动复核本条回复（{reason}），此前回答中的证据已补交校验后重新交付。
```
标签行（L251）`系统自检 · 验证器重试` 保留。

## T5 · 测试

`tests/verify_claim_api.test.ts`（identity_api 同款模式：服务不可达 skip）：
1. `sentiment_overview:风云T7` → 无 failure
2. `sentiment_overview:不存在的车系XYZ` → failure
3. 从 sentiment DB 现取一个真 post_id → `sentiment_posts:{id}` 无 failure
4. `sentiment_posts:00000000-0000-0000-0000-000000000000` → failure

grounding.test.ts 增 describe（前缀放行 3 case + 旧 8 case 回归）。

## 关键路径与里程碑

M1 = T1+T2（闸通）→ M2 = T3+T5（护栏与测试）→ M3 = T4+T6（前端 + E2E 复问）。
M1 完成即可手动 E2E；T6 全量验收在 M3。

## 风险

- **R-a 语义弱化**：overview 类引用只验"车存在"不验具体数字——与 review_tags"行存在"同粒度，数字另有台账管（数值真值集已含 sentiment 工具返回值），可接受。
- **R-b 名匹配宽**：包含匹配可能把"星愿"匹配到"小鹏星愿"？——现库 23 车无此冲突；resolveVehicleId 已用同语义跑了数月。记录为已知限制。
- **R-c 双库双连接**：/verify/claim 每请求开两条连接（惰性：仅当出现对应表的引用才开 sentiment 连接）。
