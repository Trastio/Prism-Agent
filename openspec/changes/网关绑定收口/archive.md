# 网关绑定收口 · 微 change 归档（2026-10-19）

## 问题
pi_gateway.mjs `server.listen(PORT)` 缺省绑定 **all-interfaces**（netstat 实证 0.0.0.0:9200 + [::]:9200）——网关无鉴权（user_id 自报），局域网内任何设备可直打，与登录门禁"浏览器只达 8002"的单门设计不符（pi_gateway.mjs:78 注释本就写明此意图，但缺省绑定没兑现）。

## 修复
`server.listen(PORT, '127.0.0.1', ...)` 一行（pi_gateway.mjs:822，带注释）。调用方核查：main.py PI_SERVER / prism.py 探活 / eval EVAL_PORTS 全部 127.0.0.1:9200，零影响。

## 验证
- kill + `PRISM_NO_BROWSER=1 python prism.py start` 幂等单服务重启（PID 46620）
- netstat：`127.0.0.1:9200 LISTENING`，0.0.0.0/[::] 监听消失
- `/health` 200（model=deepseek-v4-flash, needsRestart=false）；api 8002 /health 200
- 测试套件未重跑（纯绑定变更零逻辑改动；下次批跑自然回归）

## 备注
发现于"深度绑定 langfuse"方向讨论时的端口绑定实测（七个端口扫描）。同轮发现 langfuse:3000 也绑 0.0.0.0（docker 发布缺省），但该栈仅本地使用且不上云（已拍板），维持现状不动。
