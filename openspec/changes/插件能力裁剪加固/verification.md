# 插件能力裁剪加固 · Step9 Verification

## 验收 1-9

1. ✅ ALLOWED_TOOLS 单一来源（Set，复用 KNOWN_BUSINESS_TOOLS + ask_user_question）
2. ✅ N1 验证：pi 文档确认未知名静默忽略 + ask_user_question 真实注册（rpiv L305）
3. ✅ agent 模式调 setActiveTools（非注释），catch 降级 [...KNOWN_BUSINESS_TOOLS]
4. ✅ decideToolCall 仍是前缀门控（P2 不扩大）
5. 🟡 permission 回填闭环（通路确认 N2，B 生产期实测留——AUTO_APPROVE=1 开发期自动批准，生产期需实测超时拒绝）
6. ✅ settings.json 两处 extensions 删除（C）
7. ✅ EXCLUDE_TOOLS 常量 + D 单测 4 case（P1-1/P1-2 修复后真校验）
8. ✅ 12 包版本全 pin + .pi/settings.json 3 重复删（E）
9. ✅ smoke:all 5+39 + D 单测 4 + 端到端银河E5 verdict=pass

## Step8 修复
- P1-1 测试假阴性（EXCLUDE 检查改 fullAllowed）
- P1-2 测试单方向（补展开表达式断言）
- Step6 #1 verdict 落盘顺序统一

## 留下一轮
- B permission 生产期实测
- P2-1 mcp__pi_* 预存失效
- P2-2/P2-3 测试健壮性
