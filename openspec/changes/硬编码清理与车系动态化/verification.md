# 硬编码清理 · Step9 Verification（最终版）

## 验收 0-8

0. ✅ 无 .js 幽灵（find src -name "*.js" = 0）+ tsc --noEmit 零错误 + vite 加载 .tsx
1. ✅ 选海豚→4 看板海豚数据（reviews 9/sales 20/config 32）
2. ✅ 证据 src 动态（supported_by/scope 抽变量，model_id 动态）
3. ✅ 演示卡默认折叠（DemoCard 删 .js 后生效）
4. ✅ 默认空态（useState('') + enabled: !!series）
5. ✅ 空系列对话拦截（ChatView handleSend 拦 + extension setActiveTools([]) 真阻断）
6. ✅ 建议问题空时通用文案（SUGGESTIONS 函数化）
7. ✅ 车系 tab 实装（搜索+最近+高亮，localStorage try/catch）
8. ✅ tsc 零错误

## smoke:all
5 smoke + 43 单测 0 fail

## 端到端
- 海豚：reviews/sales/config 全海豚
- 空系列：agent 不分析，要求先选车系

## Step8 修复
P1-1 localStorage 崩溃 + P2-2/3/7/10/12 共 6 项

## 留下一轮（非阻塞）
P2-1/4/6/8/11/13 共 6 项数据健壮性/边界
