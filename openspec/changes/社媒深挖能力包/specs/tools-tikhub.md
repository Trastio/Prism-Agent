# Spec 1 · TikHub 工具组（工具接口层）

## 待办

- T1 makeTikhubTool 工厂 + 4 工具注册（social_search / social_post_comments / social_user_profile / social_user_posts）
- T2 ENDPOINT_MAP（design §1.1 五平台）+ normalizer（统一信封 + URL 构造 + 防御式字段映射）
- T3 信封/重试/超时/截断（401/402 语义化文案；truncateHead 50KB/2000 行；items≤30）
- T4 每轮调用上限：before_agent_start 清零 + tool_call 计数 >8 block（文案含缺口声明引导）
- T5 env：pi_gateway 读 prism-api/.env 注入 PRISM_TIKHUB_KEY；无 key → 工具 fail-closed "TikHub 未配置"
- T6 TOOL_CATEGORIES.web 扩 4 工具（白名单/tier/URL 收集三处自动派生，验证不破既有单测）
- T7 工具描述教学：引用格式（平台+URL+抓取时间+不可复算）、8 次上限、评论区金矿提示

## 设计细节

- 工具 schema（typebox）：social_search{platform:enum5, keyword:string, time_window?:enum, max_results?:≤30}；social_post_comments{platform:enum5, post_url或post_id, max?:≤50}；social_user_profile{platform:enum2(douyin|xiaohongshu), user_id(支持 sec_uid:/抖音号/分享链接)}；social_user_posts{platform:enum2, user_id, cursor?, count?:≤30}
- post_id 解析：接受完整 URL 或裸 ID（douyin.com/video/{id} → aweme_id；xiaohongshu.com/explore/{id} → note_id；m.weibo.cn/status/{id} → wid）
- profile 双入口路由：`sec_uid:` 前缀→v4；纯数字→v2(unique_id)；http 链接→从链接抽 sec_uid
- 每轮计数器导出为可测函数（单测直接调，不靠跑 pi）
- collectNameTruth 扩 keyword 参数（design §4）

## 验收

1. 4 工具注册后 smoke:all 全绿（既有 55 不回归）
2. 无 PRISM_TIKHUB_KEY：调 social_search 返回明确"未配置"错误（不崩、不静默空结果）
3. mock 信封 401/402/5xx：文案正确、5xx 重试 1 次、4xx 不重试
4. 第 9 次调用被 block 且文案含数据缺口引导
5. 归一化输出每 item 有 url（weibo 无 url 场景除外）且 _meta 带不可复算声明
6. 输出过 truncateHead（>50KB fixture 验证截断标记）

## 依赖

- PRISM_TIKHUB_KEY 可选（无 key 时全链路可测，仅真实调用不可用）
- 真实响应结构校准依赖 key 恢复（M5 前完成）
