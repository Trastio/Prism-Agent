# Spec 3 · xlsx 导出（export_document + /export）

## 待办

- T1 main.py `POST /export`：{title, filename?, sheets[]} → openpyxl（表头加粗/冻结首行/列宽自适应）→ exports/{file_id}.xlsx + manifest.json → {file_id, filename, url, sheets:n}
- T2 `GET /export/download/{file_id}`：FileResponse；file_id 必须 manifest 命中（防穿越）；正确 xlsx MIME
- T3 校验：sheets≤20 / rows≤5000/sheet / cell≤3000 字 / filename `^[A-Za-z0-9_\-一-龥.]{1,60}$`（不合法自动 fallback export-{ts}）
- T4 extension `export_document` 工具：参数同 body；返回 {url, filename}；描述教"回复正文给 markdown 链接"
- T5 vite.config.ts +/export 代理；前端零组件改动（链接渲染已有）
- T6 `GET /tikhub/status`：代理账号两端点，10min 缓存，无 key → {configured:false}

## 设计细节

- exports/ 目录进 .gitignore；manifest.json 记 {id, filename, title, created_at, sheets}（供审计/列表，不做删除管理——单机量小）
- file_id = nanoid/uuid，文件名 `{file_id}.xlsx`（下载时 FileResponse 用 manifest 里 filename 作显示名）
- openpyxl 已在 venv（3.1.5 实测）；不引 python-docx（二期）
- /export 走既有鉴权中间件链（与 /dash 同待遇）

## 验收

1. POST /export → GET download 往返：openpyxl 读回校验 sheet 名/表头/单元格内容一致
2. filename 含 `../` 或特殊字符 → fallback 名，无 500
3. rows 5001 → 422 明确错误
4. /export/download/任意不存在 id → 404
5. agent 实测：export_document 调用后回复含 markdown 链接，浏览器点开下载成功（E2E）
6. /tikhub/status 无 key 时 {configured:false} 不报错；有 key 时返回余额（M5 实测）

## 依赖

- 无外部依赖（openpyxl 已就位）；T4 依赖 Spec 1 的工具注册模式
