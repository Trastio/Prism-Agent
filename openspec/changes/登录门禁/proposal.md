# 登录门禁 · 提案

> 2026-10-15 ｜ 设计依据：`设计图总览/Prism-Agent-登录门禁方案-v1.md`（用户拍板：统一口令门，全员密码 666666）
> Step1 explore 已完成（2026-10-15，主会话实测接线面）

## 为什么做

user_id 前端自报无门禁——badcase 回流无法按真人归因、记忆缓做的硬阻塞、上云前必补。统一口令门是最小补丁。

## Step1 探查结论（相对方案的两处落点修正）

1. **网关不动，api 层统一拦截**：实测网关(9200)不直接暴露给浏览器（链路 web→api→gateway 内网下游），原方案"网关校验 token"改为 **api 层单个 FastAPI dependency 拦全部路由**（`/auth/login` 与 `/health` 豁免），等效且改动减半。
2. **门禁边界=主站 api(8002)**：dashboards(8010)/sentiment(8000)/ops(8020) 子服务端口本地阶段不拦（看板 iframe 数据源，拦了全断）；上云时收进内网。写进验收防误伤。

## 接线面（Step1 实测）

| 层 | 现状 | 改动 |
|---|---|---|
| web | `getUserId()` 自报 6 处（App.tsx:91 / ChatView.tsx:235,324 / Sidebar.tsx:27,35,54） | 新增登录页组件；fetch 带 cookie（同源 vite proxy 自动带）；未登录跳登录页；getUserId 改从 token 解出（后端以 token 为准） |
| api | 19 路由裸奔（main.py:120-1018） | +`/auth/login`（users.json 盐哈希校验→HMAC token 签发 HttpOnly cookie 7d）+全局 dependency（token→username/role，user_id 以 token 为准）+`/auth/me`；eval runner 自动登录（env 凭据） |
| gateway | 只信任 api 内网调用 | **不动** |
| users.json | 不存在 | 新建（gitignore）：`[{username, role: admin|viewer, pwhash, salt}]`；预置 admin（管理者=用户本人）+eval 两账号，密码 666666 哈希落盘 |

## 验收（方案 §6 落地版）

1. 未登录访问 api 任意业务路由 → 401；web 任意页 → 跳登录页
2. 错密码拒绝并提示；对密码进站，7 天免登录
3. admin 可编辑赋分，viewer 只读（现有权限行为不回归）
4. eval runner 自动登录 → 1 题 smoke + 门禁 E2E 1 题跑通
5. users.json 无明文密码；token 密钥在 env（gitignore）
6. web tsc 0 错 + build 过 + smoke 全绿 + api 既有单测零回归
7. 门禁边界：8010/8000/8020 不拦（文档化）

## 任务

见 tasks.md。轻量十步：Step5 施工=子代理（fork 型重试制）；Step7 隔离审查=子代理（代码全文内嵌、磁盘提取）——鉴权敏感，审查不省。
