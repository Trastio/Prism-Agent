# 插件能力裁剪加固 · Step8 Receiving Code Review

## 已修
- P1-1 测试假阴性：EXCLUDE_TOOLS ∩ ALLOWED_TOOLS 只校验 ask_user_question → 改用 fullAllowed=[...knownTools, 'ask_user_question'] 完整检查
- P1-2 测试单方向：ALLOWED_TOOLS 未验证 KNOWN⊆ALLOWED → 补断言源码含展开表达式
- Step6 #1 verdict 落盘三联顺序不一致 → 统一 appendEntry→writeVerdictFile→appendTrajectory

## 留下一轮（非阻塞）
- P2-1 mcp__pi_* 条目对直接注册型插件失效（预存，闸2 白名单已兜底）
- P2-2 N12 测试未断言包数=12 + 预发布版本
- P2-3 regFromObj 正则假设 name 首属性
- B permission 回填闭环实测（生产期 AUTO_APPROVE 关时）
- Step6 #2-#6 其他简化项
