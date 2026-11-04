# Spec 2.6 · pi 集成层

> Step 2 注入通道 + Step 5 重启补漏 + Step 6 verdict。前置 [design.md](./design.md)。

## 待办
- 2.1-2.4 series_key 全链路通道（前端→FastAPI→gateway→prompt）
- 5.1 重启 pi_gateway + FastAPI + 清孤儿 vite
- 5.2 /health 就绪探针 + 进程崩溃自动重启 + 启动时间戳
- 5.3 /ui-response main.py 转发 + vite 代理 + AUTO_APPROVE env 策略
- 5.4 --exclude-tools 补 mcp/记忆/子代理
- 5.5 模式分流 scope + setActiveTools
- 5.6 /chat/stream 透传 session_id + session_info 事件
- 5.7 可配超时 PRISM_TURN_TIMEOUT
- 5.8 密钥移出源码（MEM0_API_KEY）
- 5.9 视图库只读 + 清残留 prism_views.db
- 5.11 vite 代理 /events

## 设计细节

**series_key + scope 通道（Step2 核心，Gap 3 修正）**：
- 前端 composer 提交：`{message, user_id, series_key, session_id, scope}`
- main.py /chat/stream（147-163）：body 增 series_key + scope 透传 pi_gateway
- pi_gateway /chat（300-311）：读 series_key + scope，拼进 prompt
  ```js
  const ctxPrefix = `[ctx: series_key=${series_key}, scope=${scope}]\n`;
  rpc.send('prompt', { message: ctxPrefix + message });
  ```
- before_agent_start 解析前缀填 SYSTEM.md {series_key} + 读 scope 调 pi.setActiveTools

**5.2 进程守护**：
- /health（293-297）增返回 `{startedAt, fileMtime, pid}`
- proc.on('exit')（95-103）：标记 disposed + **自动重新 spawn**（非惰性）—— 加 `if (!this.manuallyDisposed) setTimeout(() => respawn(), 1000)`
- 启动时间戳：`this.startedAt = Date.now()` 构造时记录
- 文件 mtime：fs.statSync(pi_gateway.mjs).mtime，与 startedAt 比对（mtime>startedAt 提示需重启）

**5.3 /ui-response**：
- main.py 加 POST /ui-response 转发到 pi_gateway:9100
- vite.config 加 '/ui-response' 代理
- AUTO_APPROVE env 策略：开发 PRISM_AUTO_APPROVE_UI=1 自动批准；生产 unset 走前端弹框回填
- uiRequests Map 加超时清理（30s 无回填→abort）

**5.4 --exclude-tools**：
- pi_gateway:252 args 当前 `['--mode','rpc','--model','deepseek-v4-flash','--approve','--session-dir',...,'-e',...]`
- 加 `--exclude-tools bash,read,write,edit,glob,grep,mcp__*,pi-memory,pi-subagents,pi-web-access`
- 验证：trace 无 bash/read

**5.5 模式分流（Gap 3 修正：setActiveTools 是 extension API）**：
- scope 字段：bi_reviews / bi_sales / bi_config / agent
- scope 拼进 prompt 前缀（同 series_key）
- **extension before_agent_start 读 scope，调 `pi.setActiveTools(allowedForScope)`**：
  - bi_reviews→['query_reviews','resolve_series']
  - bi_sales→['query_sales','resolve_series']
  - bi_config→['query_config','resolve_series']
  - agent→全 23 工具
- 网关不调 setActiveTools（它是 extension API，extensions.md:1371/1677）

**5.7 可配超时**：
- pi_gateway:180-188 当前硬编码 300s
- 改 `const TURN_TIMEOUT = parseInt(process.env.PRISM_TURN_TIMEOUT || '300') * 1000`

**5.8 密钥移出**：
- pi_gateway:259 删 `MEM0_API_KEY: process.env.MEM0_API_KEY || 'm0-...'` 兜底
- 改 `MEM0_API_KEY: process.env.MEM0_API_KEY`（无则 undefined，mem0 降级）
- .env.example 文档化

**5.9 视图库只读**：
- src/registry/datasource.ts openPrismViews 加 `{readonly:true}`（better-sqlite3）
- 清理 0 字节残留 prism_views.db（fs.statSync size===0→删）

## 验收
- series_key + scope 从前端到 prompt 全链路通（before_agent_start 填充 + setActiveTools 生效）
- /health 返回 startedAt + mtime
- 进程崩溃→1s 内自动重启
- /ui-response 前端→FastAPI→pi_gateway 回填通
- trace 无 bash/read
- BI 模式 scope 限制工具白名单
- session_id 透传 + session_info 事件
- PRISM_TURN_TIMEOUT 生效
- grep MEM0_API_KEY 源码无硬编码兜底
- prism_views.db 只读打开

## 依赖
- Step 1 extension 接线（setActiveTools 工具白名单）
- Step 2.6 /identity/resolve（resolve_series 工具调它）
