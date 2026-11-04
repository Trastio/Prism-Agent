# Prism 运维手册（OPERATIONS）

> 2026-11-02 上线收敛版。只写操作步骤，不写任何密码。

## 1. 服务与访问

| 服务 | 端口 | 访问方式 |
|---|---|---|
| 主站（前端 + API） | 80/443 | `https://prism-agent.example.com`（登录门禁） |
| 北极星看板 | 8020 | **仅绑 127.0.0.1**，通过 SSH 隧道：`ssh -L 8020:127.0.0.1:8020 root@203.0.113.10`，本地开 `http://127.0.0.1:8020` |
| 巡检报告 | 443 | 登录主站后看板页顶部「系统健康」条；接口 `GET /health/report`（需登录） |

## 2. 定时任务（服务器 ECS crontab）

| 时间 | 任务 | 说明 |
|---|---|---|
| 03:00 | 舆情采集 `daily_update --all` | 容器内运行，写入 `/root/prism/data/vehicle_sentiment.db` |
| 03:00（周日） | 配置快照周更（工位机任务 `PrismConfigWeekly`） | 写 `deploy/data/autohome.db` |
| 04:00（周日） | 口碑周更（工位机任务 `PrismKoubeiWeekly`） | 采集后整库 push 云端，配置数据一并上云 |
| 04:30 | 云端备份 `backup.sh` | 保留 7 天 |
| 08:00 | 每日巡检 `daily_health.py` | 生成 `/root/prism/data/health/latest.json` + 当日 md |

> 工位机任务在「用户登录后」运行；服务器任务在 crontab。

## 3. 每日/每周检查

1. 打开主站 → 看板页顶部健康条：
   - 「全部正常」→ 无需操作；
   - 「异常 N 项」→ 按名称排查（服务/舆情/口碑/配置/销量/埋点/证书）。
2. 每周一看上周日任务是否都成功（配置、口碑、备份）。
3. 每月看一次证书剩余天数（健康条已含，阈值 <14 天）。

## 4. 手动触发

```bash
# 舆情采集（服务器）
docker exec -d prism-prism-sentiment-1 sh -c "cd /app/prism-sentiment && python scripts/daily_update.py --all >> /app/prism-sentiment/data/manual_run.log 2>&1"

# 每日巡检（服务器）
python3 /root/prism/deploy/daily_health.py

# 全链路 smoke（服务器）
cd /root/prism/deploy && PRISM_SMOKE_USER=admin PRISM_SMOKE_PASS='***' bash smoke_remote.sh

# 口碑/配置上云（工位机）
python prism.py koubei-weekly --push-only

# 销量导入（F4，CAM 月末片到齐后）
cd prism-dashboards
python scripts/import_sales_excel.py ..\业务数据\CAM终端价格监测-<M>月末.xlsx
python scripts/verify_sales_import.py --db ..\deploy\data\autohome.db --expect-month <M>月末
# 校验通过后再 push 上云：
python ..\prism.py koubei-weekly --push-only
```

## 5. 数据源与写入路径

| 数据 | 源 | 唯一写入位置 | 上云方式 |
|---|---|---|---|
| 舆情 | TikHub + 车质网等 | 云端 `/root/prism/data/vehicle_sentiment.db` | 云原生，无需推送 |
| 口碑 | 汽车之家口碑 | 工位机 `deploy/data/autohome.db` | 周日口碑周更末尾整库 push |
| 配置 | 汽车之家配置接口 | 工位机 `deploy/data/autohome.db` | 随口碑 push 上云 |
| 销量 | CAM 半月片 xlsx | 工位机 `deploy/data/autohome.db` | 随口碑 push 上云 |

> 本地服务（8002/8010/pi 工具）已统一读 `deploy/data/autohome.db`。
> `prism-dashboards/data/autohome.db` 是历史副本，目前只作 eval 快照源（M0x 结束后改指向 deploy/data 再归档）。

## 6. 回滚

| 变更 | 回滚 |
|---|---|
| compose 任何改动 | 服务器 `deploy/docker-compose.yml.bak-*` 覆盖后 `docker compose up -d` |
| nginx 反代 | `nginx/locations.inc.bak-a2` 覆盖后 `nginx -s reload` |
| crontab | `crontab /root/prism/logs/crontab.bak-20261102` |
| 前端 | 改回 nginx 静态挂载前的镜像内版本（移除 `./web` 挂载后重启 nginx） |

## 7. 已知边界

- 不做即时告警：故障最长 24h 后在每日汇总中发现；
- 不做异地灾备：备份与数据同机；
- 单模型供应商：DeepSeek 不可用时无降级路径；
- 工位机任务依赖开机/登录。
