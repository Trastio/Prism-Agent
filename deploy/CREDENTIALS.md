# Prism 凭据管理流程（CREDENTIALS）

> 本文件只写**流程**，不写任何密码明文。
> 密码只保存在服务器 `deploy/.env` / `prism-api/data/users.json`（哈希），不入库、不进聊天记录。

## 1. 谁持有

| 凭据 | 位置 | 持有人 |
|---|---|---|
| 登录共享口令（哈希） | 服务器 `data/api/users.json` | 管理者（用户本人） |
| `PRISM_AUTH_SECRET` | 服务器 `deploy/.env` | 管理者 |
| `PRISM_MANAGER_PASSWORD` | 服务器 `deploy/.env` | 管理者 |
| `DEEPSEEK_API_KEY` | 服务器 `deploy/.env` | 管理者 |
| `TIKHUB_KEY_PRISM` | 服务器 `deploy/.env` | 管理者 |
| SSH 部署口令 | 本地 `deploy/.sshpass` | 管理者 |

## 2. 登录口令重置（影响全部使用者）

1. 登录服务器，备份：`cp data/api/users.json data/api/users.json.bak-$(date +%Y%m%d%H%M)`；
2. 生成新口令的哈希（在 `prism-api` 容器内执行，避免把明文写进 shell 历史）：
   ```
   docker exec -it prism-prism-api-1 python -c "import secrets,hashlib; s=secrets.token_hex(16); p=input('new password: '); print('salt',s); print('hash',hashlib.scrypt(p.encode(),salt=bytes.fromhex(s),n=2**14,r=8,p=1).hex())"
   ```
3. 用输出的 `salt`/`hash` 覆盖 `users.json` 的 `salt`/`pwhash`（保留 `admins`）；
4. `docker restart prism-prism-api-1`；
5. 旧口令立即失效，**提前通知所有人**新的获取方式（不要贴在公开群）。

## 3. `PRISM_AUTH_SECRET` 轮换

1. 生成新值：`openssl rand -hex 32`；
2. 更新 `deploy/.env` 的 `PRISM_AUTH_SECRET`；
3. `docker compose up -d prism-api`（重启后所有已登录 cookie 失效，使用者需重新登录）；
4. 低峰执行，提前通知。

## 4. 第三方 key 轮换

- DeepSeek：在供应商控制台吊销旧 key → 写新值到 `deploy/.env` → 重启 `prism-api` 与 `prism-sentiment`；
- TikHub：同理，重启 `prism-api` 与 `prism-sentiment`；
- 轮换后跑一次 `bash deploy/smoke_remote.sh` 确认对话与采集仍可用。

## 5. 事故处理

- 怀疑泄露：立即执行 §3（`PRISM_AUTH_SECRET`）与 §2（登录口令），并轮换全部第三方 key；
- `users.json` 损坏：服务会自动重建并生成**随机**初始口令（仅启动日志打印一次），按日志记录后立即按 §2 改成正式口令。

## 6. 禁止事项

- 不把密码写入仓库、脚本、聊天、工单；
- 不在命令行直接明文传密码（用 stdin 或交互输入）；
- 不把 `.env.prod`、`.sshpass`、`users.json` 提交到 git。
