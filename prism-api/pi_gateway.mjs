/**
 * Prism-Agent · pi_gateway.mjs（Node 常驻 HTTP 服务）
 *
 * 方案 B：用 pi --mode rpc 子进程（每用户一个），进程级隔离。
 * Node 网关管理 RPC 子进程池，FastAPI 转发 HTTP 到这里。
 *
 * 不造轮子：HTTP 接缝是项目必需（pi 不做 HTTP server）；
 * RPC 协议 / SessionManager / 事件流全用 pi 官方。
 */

import http from 'node:http';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { resolve, sep } from 'node:path';
import { mkdirSync, statSync, readFileSync, existsSync, writeFileSync, unlinkSync, appendFileSync } from 'node:fs';

const GATEWAY_PATH = new URL(import.meta.url).pathname.replace(/^\//, '');
const STARTED_AT = new Date().toISOString();
import { StringDecoder } from 'node:string_decoder';
// C2（2026-10-14 评估迭代基建包）：mapEvent 抽到纯模块（本文件 import 即 listen，
// 内联函数不可单测）；auto_retry_start/end 新 case 见 map_event.mjs
import { mapEvent } from './map_event.mjs';
// Block B（判分器修复与七题处置，2026-10-27）：用户中止轮残留注记——纯函数外置
// （multi-12 实证：被中止轮的部分产出留在会话历史，下一轮自然引用=残留否决）
import { withAbortNote, stripAbortNoteFromMessages } from './abort_note.mjs';

const PROJECT_ROOT = resolve(import.meta.dirname, '..');
const PORT = parseInt(process.env.PRISM_GATEWAY_PORT || '9200');

// 社媒深挖能力包 M1：读 prism-api/.env 的 TIKHUB_KEY_PRISM（缓存一次；无文件/无键 → undefined）
// P2 修复：对齐 dotenv 语义——去首尾引号 + 去行内注释（否则与 main.py load_dotenv 双源分歧）
let _tikhubKeyCache;
function readServiceTokenFromFile() {
  try {
    return readFileSync(resolve(PROJECT_ROOT, '.pi/service_token'), 'utf8').trim();
  } catch { return ''; }
}

function readTikhubKeyFromFile() {
  if (_tikhubKeyCache !== undefined) return _tikhubKeyCache;
  _tikhubKeyCache = null;
  try {
    const text = readFileSync(resolve(PROJECT_ROOT, 'prism-api/.env'), 'utf8');
    const m = text.match(/^TIKHUB_KEY_PRISM\s*=\s*(.+)$/m);
    if (m) {
      let v = m[1].trim();
      const hashIdx = v.indexOf(' #');
      if (hashIdx !== -1) v = v.slice(0, hashIdx).trim();
      v = v.replace(/^["']|["']$/g, '');
      if (v) _tikhubKeyCache = v;
    }
  } catch {}
  return _tikhubKeyCache;
}

// D/N4：EXCLUDE_TOOLS 可导出常量（供单测引用，防双源漂移）
// 闸 1：denylist 兜底（主要防线是闸 2 setActiveTools 白名单）
export const EXCLUDE_TOOLS = [
  'bash', 'powershell', 'edit', 'write', 'read', 'grep', 'find', 'ls',
  'mcp__pi_memory', 'mcp__pi-subagents', 'mcp__pi-memory-mem0',
  'mcp__pi-mcp-adapter', 'mcp__pi-todo', 'mcp__pi-workspace-history',
];
const PI_BIN = process.env.PI_BIN || resolve(PROJECT_ROOT, 'pi-windows-x64/pi.exe');
const SESSIONS_DIR = resolve(PROJECT_ROOT, '.pi/sessions');

// ---------------------------------------------------------------------------
// P0: user_id 校验（防路径穿越）
// ---------------------------------------------------------------------------
function validateUserId(uid) {
  if (typeof uid !== 'string' || !/^[A-Za-z0-9_-]+$/.test(uid)) {
    return null;
  }
  return uid;
}

// P1#7：auto-approve gate（生产期不设 PRISM_AUTO_APPROVE_UI=1 则拒绝）
const AUTO_APPROVE = process.env.PRISM_AUTO_APPROVE_UI === '1';

// 多轮评估批 change T3：eval 模拟应答第三态（仅 eval 网关 9201 注入，prism.py eval start）——
// ui_request 不抢答，转发事件流让 runner 按题级 ui_strategy 模拟用户应答（skill-03 被瞎代答根治）。
// 生产（9200）无此 env：二态行为逐行不变。runner 侧 30s 兜底 + pi --approve 已拦 permission 层。
const EVAL_UI_SIM = process.env.PRISM_EVAL_UI_SIM === '1';

// P1#5：同 userId 串行锁
const inflightLocks = new Map();  // userId → Promise

// RPC 原始事件 → 前端友好格式映射
// 块5 B1：事件契约补全——pi RPC 事件全集对齐，显式标注透传/丢弃+原因
// C2（2026-10-14）：函数体抽到 map_event.mjs（pi_gateway import 时即 listen，
// 内联不可单测）；auto_retry_start/end 补 case 见该模块

// ---------------------------------------------------------------------------
// RPC 子进程管理
// ---------------------------------------------------------------------------
class RpcClient {
  constructor(proc, userId) {
    this.proc = proc;
    this.userId = userId;
    this.sessionId = userId;  // P1#22：供 session_info 事件用（pi 内部 sessionId 在 session_start 后异步获取）
    this.buffer = '';
    this.decoder = new StringDecoder('utf-8');
    this.pending = new Map();
    this.lastAbortAt = 0;   // S7-d：最近一次 abort 时刻——/chat 据此等中止余波（pi 在 abort 后 ~1s 仍吐旧轮事件）
    this.abortPending = false;   // S8 P1-1：/chat 余波等待期间到达的 abort 意图——S7-b 清队会吞合成 aborted，用标志补记
    // Block B：用户中止标记（值为被中止的会话 id）——/abort 落、/chat 同会话下一轮
    // 一次性消费（prompt 尾部附"勿引用被中止内容"注记，见 abort_note.mjs）
    this.pendingAbortNote = null;
    this.uiRequests = new Map();   // ui_request id → msg（等前端回填）
    this.eventQueue = [];           // 事件队列（待消费）
    this.eventWaiters = [];         // 等待事件的消费者
    this.lastActive = Date.now();
    this.disposed = false;

    proc.stdout.on('data', (chunk) => this._onData(chunk));
    proc.stderr.on('data', (d) => {
      const s = d.toString().trim();
      if (s) console.error(`[pi:${userId}]`, s.slice(0, 200));
    });
    proc.on('exit', (code) => {
      this.disposed = true;
      this.eventWaiters.forEach(fn => fn({ type: 'error', data: { message: `pi exited (code=${code})` } }));
      this.eventWaiters = [];
      this.pending.forEach(p => p.reject(new Error(`pi exited (code=${code})`)));
      this.pending.clear();
      console.error(`[pi_gateway] ${userId} exited code=${code}`);
      // P1-进程守护：崩溃自动 respawn（非手动 dispose 时）
      if (!this.manuallyDisposed) {
        console.error(`[pi_gateway] ${userId} 崩溃，1s 后自动 respawn`);
        setTimeout(() => {
          try { getOrCreateRpc(userId); } catch (e) { console.error(`[pi_gateway] respawn ${userId} 失败:`, e.message); }
        }, 1000);
      }
    });
  }

  async writeSafe(str) {
    if (this.disposed) throw new Error('pi process disposed');
    const ok = this.proc.stdin.write(str);
    if (!ok) {
      await new Promise(resolve => this.proc.stdin.once('drain', resolve));
    }
  }

  _onData(chunk) {
    // P2#12：用 StringDecoder 处理多字节截断
    this.buffer += this.decoder.write(chunk);
    let idx;
    // 手写 indexOf('\n') 切分（不能用 readline，U+2028/U+2029 拆行）
    while ((idx = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 1);
      if (line.trim()) {
        try {
          this._handleLine(JSON.parse(line));
        } catch (e) {
          console.error(`[pi:${this.userId}] parse error:`, line.slice(0, 100));
        }
      }
    }
  }

  _handleLine(msg) {
    this.lastActive = Date.now();
    // extension_ui_request：dialog 类（select/confirm/input）转前端，fire-and-forget 忽略
    if (msg.type === 'extension_ui_request') {
      if (['select', 'confirm', 'input'].includes(msg.method)) {
        if (EVAL_UI_SIM) {
          // 多轮评估批 T3 第三态：不抢答——转发 ui_request 事件给消费方（runner 模拟用户按
          // 题级 ui_strategy 应答，POST /ui-response 回填；无策略题 runner 默认代答=与旧 AUTO_APPROVE 等价）
          this.uiRequests.set(msg.id, msg);
          this.eventQueue.push({
            type: 'ui_request',
            data: { id: msg.id, method: msg.method, title: msg.title, options: msg.options, message: msg.message }
          });
          const waiter = this.eventWaiters.shift();
          if (waiter) waiter();
          // 30s 兜底：事件丢失/应答失败时默认代答（respondUi 的 has() 守卫天然防双响应）——
          // 防 pi 等 ui 回填挂死拖垮整池（首冒烟实证：404 回填→300s 超时+串行锁毒化重跑）
          setTimeout(() => {
            if (!this.uiRequests.has(msg.id)) return;
            this.uiRequests.delete(msg.id);
            const fallback = msg.method === 'select' ? (msg.options?.[0]) : msg.method === 'confirm' ? true : '';
            this.writeSafe(JSON.stringify({ type: 'extension_ui_response', id: msg.id, value: fallback }) + '\n')
              .catch(() => {});
            console.warn(`[ui-sim] 30s 兜底代答（未收到回填）: ${msg.method} "${(msg.title || '').slice(0, 30)}"`);
          }, 30_000);
        } else if (AUTO_APPROVE) {
          // 开发期自动批准
          const val = msg.method === 'select' ? (msg.options?.[0]) : msg.method === 'confirm' ? true : '';
          this.writeSafe(JSON.stringify({ type: 'extension_ui_response', id: msg.id, value: val }) + '\n').catch(() => {});
        } else {
          // 转发给前端：推入事件队列（前端收到后 POST /ui-response 回填）
          this.uiRequests.set(msg.id, msg);
          this.eventQueue.push({
            type: 'ui_request',
            data: { id: msg.id, method: msg.method, title: msg.title, options: msg.options, message: msg.message }
          });
          const waiter = this.eventWaiters.shift();
          if (waiter) waiter();
        }
      }
      // fire-and-forget（notify/setStatus 等）：忽略
      return;
    }
    // RPC 响应（有 id 匹配 pending）
    if (msg.id && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (p.resolve) p.resolve(msg);
    } else if (msg.id && !this.pending.has(msg.id)) {
      // 迟到响应：丢弃
    } else {
      // 事件：入队，唤醒等待者从队列取
      this.eventQueue.push(msg);
      const waiter = this.eventWaiters.shift();
      if (waiter) waiter();
    }
  }

  async send(type, params = {}) {
    if (this.disposed) throw new Error('pi process disposed');
    const id = randomUUID();
    this.pending.set(id, { resolve: null, reject: null, timedOut: false });
    return new Promise((resolve, reject) => {
      // S8 P2-1：响应到达即清超时定时器（此前每个 RPC 残留定时器至 300s 到期）
      const timer = setTimeout(async () => {
        if (this.pending.has(id)) {
          this.pending.get(id).timedOut = true;
          this.pending.delete(id);
          reject(new Error(`RPC timeout: ${type}`));
          // 发 abort 中断 pi（P1#6）
          try { await this.writeSafe(JSON.stringify({ id: randomUUID(), type: 'abort' }) + '\n'); } catch {}
          this.lastAbortAt = Date.now();   // S7-d：超时中止同样记余波时刻
        }
      }, parseInt(process.env.PRISM_TURN_TIMEOUT || '300') * 1000);
      const p = this.pending.get(id);
      p.resolve = (v) => { clearTimeout(timer); resolve(v); };
      p.reject = (e) => { clearTimeout(timer); reject(e); };
      const msg = { id, type, ...params };
      // S8 P1-2：写失败（如 pi 已死 EPIPE）立即清 pending——否则残留 300s 后
      // 超时块给"重生进程上的新轮"补刀 abort（隔离审查实测推演路径）
      this.writeSafe(JSON.stringify(msg) + '\n').catch((err) => { this.pending.delete(id); reject(err); });
    });
  }

  nextEvent() {
    if (this.eventQueue.length > 0) {
      return Promise.resolve(this.eventQueue.shift());
    }
    // exit/abort 路径以参数直接传入事件——须优先用入参，否则 resolve(undefined) 导致
    // mapEvent 读 undefined.type 崩（2026-10-07 gatetest6 实测：pi 崩溃后客户端收到残缺 error）
    return new Promise(resolve => this.eventWaiters.push((evt) => resolve(evt !== undefined ? evt : this.eventQueue.shift())));
  }

  // B3：前端回填 UI 响应
  async respondUi(id, value, cancelled = false) {
    if (!this.uiRequests.has(id)) return;
    this.uiRequests.delete(id);
    const resp = { type: 'extension_ui_response', id };
    if (cancelled) resp.cancelled = true;
    else resp.value = value;
    await this.writeSafe(JSON.stringify(resp) + '\n');
  }

  async abort() {
    // S7-d：记录中止时刻（/chat 余波等待用）
    this.lastAbortAt = Date.now();
    // S8 P1-1：若此刻无 /chat 循环在读（新 /chat 在 S7-d 睡眠），合成 aborted 会被
    // S7-b 清队吞掉——置标志，让 /chat 醒来后补走 aborted 收尾（吞掉用户中止）
    this.abortPending = true;
    // P1#4：abort 后推 aborted 事件让 /chat 循环退出
    this.eventQueue.push({ type: 'aborted', data: {} });
    const w = this.eventWaiters.shift();
    if (w) w();
    try { await this.send('abort'); } catch {}
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.manuallyDisposed = true;  // P0-1：防 exit handler respawn
    // P2#13：Windows 上 SIGTERM 无效，直接 kill
    try { this.proc.kill(); } catch {}
    // 通知所有等待者
    this.eventWaiters.forEach(fn => fn());
    this.eventWaiters = [];
    this.pending.forEach(p => { if (p.reject) p.reject(new Error('disposed')); });
    this.pending.clear();
  }
}

// ---------------------------------------------------------------------------
// 子进程池（每用户一 RPC 进程）
// ---------------------------------------------------------------------------
// 块5 C：进程池治理——MAX_POOL 上限 + LRU 淘汰 + 排队
const MAX_POOL = parseInt(process.env.PRISM_MAX_POOL || '12');
const pool = new Map();  // userId → RpcClient

function getOrCreateRpc(userId) {
  if (pool.has(userId)) {
    const c = pool.get(userId);
    if (c.disposed) {
      pool.delete(userId);
    } else {
      c.lastActive = Date.now();  // LRU 更新
      return c;
    }
  }

  // 块5 C：池满 → LRU 淘汰最空闲进程
  if (pool.size >= MAX_POOL) {
    let oldestUid = null, oldestTime = Infinity;
    for (const [uid, c] of pool) {
      if (c.lastActive < oldestTime && !inflightLocks.has(uid)) {
        oldestTime = c.lastActive; oldestUid = uid;
      }
    }
    if (oldestUid) {
      const old = pool.get(oldestUid);
      try { old.dispose(); } catch {}
      pool.delete(oldestUid);
      console.error(`[pi_gateway] LRU 淘汰 ${oldestUid}（池满 ${pool.size}/${MAX_POOL}）`);
    } else {
      // 所有进程都在忙 → 排队（不拒绝，等 inflightLocks 释放）
      console.error(`[pi_gateway] 池满且全部在忙，${userId} 排队等待`);
    }
  }

  // 确保用户 session 目录存在
  const userDir = resolve(SESSIONS_DIR, userId);
  mkdirSync(userDir, { recursive: true });

  // 启动 pi --mode rpc（T-5.4：exclude-tools 补 mcp/记忆/子代理；T-5.8：密钥移出源码）
  const args = ['--mode', 'rpc', '--model', 'deepseek-v4-flash', '--approve', '--session-dir', userDir,
    '--exclude-tools', EXCLUDE_TOOLS.join(','),
    // 取代性实验 B 系列（审查未尽①）：extension 路径 env 化——挑战者网关 :9202 用
    // PRISM_PI_EXTENSION=.pi/extensions-available/challenger-b1/index.ts + PRISM_CHALLENGER=1 布防；
    // ⚠ challenger 不放 .pi/extensions/ 下（pi 自动发现会在每个 spawn 加载它——P2 批跑事故：no-op 布防
    //   挡住工具污染但 extension loader 报 parse error 致 pi 异常退出，55/189 跑次空回复作废，2026-10-27）
    '-e', resolve(PROJECT_ROOT, process.env.PRISM_PI_EXTENSION || '.pi/extensions/prism-guardrails/index.ts')];
  const proc = spawn(PI_BIN, args, {
    // 挑战者臂隔离（B 系列）：pi 对 cwd 做 .pi/extensions 项目级自动发现（信任后加载）——
    // 挑战者网关注入 PRISM_PI_CWD=空工作目录（未信任、无 .pi/）→ guardrails 不会混入，
    // 挑战者扩展仅经 -e 显式加载；A 系/生产缺省 cwd=PROJECT_ROOT 零变化。
    cwd: process.env.PRISM_PI_CWD || PROJECT_ROOT,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PI_CODING_AGENT_DIR: resolve(PROJECT_ROOT, '.pi/agent-minimal'),
      // T-5.8：MEM0_API_KEY 移出源码（无 env 则不传，mem0 降级）
      ...(process.env.MEM0_API_KEY ? { MEM0_API_KEY: process.env.MEM0_API_KEY } : {}),
      // 社媒深挖能力包 M1：TikHub key 单源在 prism-api/.env（prism-api /tikhub/status 共用）；
      // 进程 env 已有 PRISM_TIKHUB_KEY 则优先（测试通道）
      ...(process.env.PRISM_TIKHUB_KEY || readTikhubKeyFromFile()
        ? { PRISM_TIKHUB_KEY: process.env.PRISM_TIKHUB_KEY || readTikhubKeyFromFile() }
        : {}),
      // 服务令牌（2026-10-18）：注入 pi 进程，extension 以 X-Prism-Service 头过 FastAPI 门禁
      ...(readServiceTokenFromFile() ? { PRISM_SERVICE_TOKEN: readServiceTokenFromFile() } : {}),
    },
  });

  const client = new RpcClient(proc, userId);
  pool.set(userId, client);
  console.error(`[pi_gateway] started pi rpc for ${userId} (pid=${proc.pid})`);
  return client;
}

// 超时清理（30 分钟无活动 → dispose）
setInterval(() => {
  const now = Date.now();
  for (const [uid, client] of pool) {
    if (now - client.lastActive > 30 * 60 * 1000) {
      console.error(`[pi_gateway] timeout cleanup ${uid}`);
      client.dispose();
      pool.delete(uid);
    }
  }
}, 60 * 1000);

// ---------------------------------------------------------------------------
// 会话显示名 sidecar（B4 迁移收尾）：SESSIONS_DIR/{userId}/names.json
// 决策：重命名不走 RPC set_session_name（仅作用于活跃会话，切来切去与在途对话竞态）；
// 列表显示的单一真值 = sidecar。建会话带 title 时镜像写入，pi 侧 sessionName 仅供其自身 export/UI。
// ---------------------------------------------------------------------------
function loadSessionNames(userId) {
  try { return JSON.parse(readFileSync(resolve(SESSIONS_DIR, userId, 'names.json'), 'utf8')); }
  catch { return {}; }
}
function saveSessionNames(userId, names) {
  const dir = resolve(SESSIONS_DIR, userId);
  mkdirSync(dir, { recursive: true });
  writeFileSync(resolve(dir, 'names.json'), JSON.stringify(names, null, 2));
}

// ---------------------------------------------------------------------------
// HTTP 服务
// ---------------------------------------------------------------------------
// CORS 来源：默认保持本机开发值，云上由 PRISM_ALLOWED_ORIGIN 覆盖（不设时行为不变）
const ALLOWED_ORIGIN = process.env.PRISM_ALLOWED_ORIGIN || 'http://localhost:5173';

const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  const url = new URL(req.url, `http://localhost:${PORT}`);

  // GET /health（T-5.2：增 startedAt + fileMtime + pool 状态）
  if (url.pathname === '/health') {
    const fileMtime = (() => { try { return statSync(GATEWAY_PATH).mtime.toISOString(); } catch { return null; } })();
    const poolInfo = {};
    for (const [uid, c] of pool) poolInfo[uid] = { disposed: c.disposed, lastActive: new Date(c.lastActive).toISOString() };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'ok', model: 'deepseek-v4-flash', port: PORT,
      startedAt: STARTED_AT, fileMtime,
      needsRestart: fileMtime && new Date(fileMtime) > new Date(STARTED_AT),
      turnTimeout: parseInt(process.env.PRISM_TURN_TIMEOUT || '300'),
      maxPool: MAX_POOL,
      poolSize: pool.size, pool: poolInfo,
    }));
    return;
  }

  // POST /chat
  if (url.pathname === '/chat' && req.method === 'POST') {
    const body = await readBody(req);
    let parsed;
    try { parsed = JSON.parse(body); } catch { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid json' })); return; }

    const userId = validateUserId(parsed.user_id || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }

    const message = parsed.message;
    if (typeof message !== 'string' || !message.trim()) {
      res.writeHead(400); res.end(JSON.stringify({ error: 'message required' })); return;
    }

    // T-2.3：series_key + scope 拼进 prompt 前缀（before_agent_start 解析）
    const seriesKey = typeof parsed.series_key === 'string' && parsed.series_key.trim()
      ? parsed.series_key.trim() : '';
    const scope = typeof parsed.scope === 'string' && parsed.scope.trim()
      ? parsed.scope.trim() : 'agent';

    const promptMessage = message;  // 不再拼前缀

    // P1-5 修复：锁检查移到 writeHead 之前（防 double writeHead 抛 ERR_HTTP_HEADERS_SENT）
    const prevLock = inflightLocks.get(userId);
    if (prevLock) {
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
      res.write(JSON.stringify({ type: 'error', data: { message: '上一个请求仍在进行中' } }) + '\n');
      res.end();
      return;
    }
    inflightLocks.set(userId, true);
    let lockSet = true;

    // S8 P2-4：先写响应头再等余波——等待最长 2.5s，无头期间前端零反馈
    res.writeHead(200, {
      'Content-Type': 'application/x-ndjson',
      'Cache-Control': 'no-cache',
    });

    // S7-d：中止余波等待——pi 在 abort 后 ~1s 内仍吐旧轮事件（tool_result/settled 尾随，
    // abort_race3/4 实测两种泄漏形态），新 prompt 立即发出会与之交织吃掉新轮。
    // 等余波窗口（2.5s）过了再清队列、发 prompt。
    const rpcPre = pool.get(userId);
    if (rpcPre && !rpcPre.disposed && rpcPre.lastAbortAt) {
      const sinceAbort = Date.now() - rpcPre.lastAbortAt;
      if (sinceAbort < 2500) await new Promise(r => setTimeout(r, 2500 - sinceAbort));
    }
    // S7-b：余波过后清残渣，新流从干净起点开始
    if (rpcPre && !rpcPre.disposed) rpcPre.eventQueue.length = 0;

    let rpc = null;
    let finished = false;
    let abortFlagSession = null;   // Block B：本轮消费掉的用户中止标记（发送失败时归还）
    try {
      rpc = getOrCreateRpc(userId);

      // S8 P1-4：客户端断连即停轮（服务端对齐契约4"断线即中止"，双保险——
      // 前端补 abort 失败时网关不再空跑到自然结束、锁滞留）
      res.on('close', () => { if (!finished && rpc && !rpc.disposed) { rpc.abort().catch(() => {}).finally(() => { rpc.abortPending = false; }); } });   // S8-P1-1fix：内部 abort 勿带意图
      // S8 P1-4 续：余波等待期间客户端已断开 → 不再发 prompt
      if (res.destroyed) { finished = true; return; }

      // S8 P1-1：余波等待期间用户点了中止（abort() 的合成 aborted 事件被 S7-b 清队吞掉）
      // → 补走 aborted 收尾，不吞用户操作
      if (rpc.abortPending) {
        rpc.abortPending = false;
        res.write(JSON.stringify({ type: 'aborted', data: {} }) + '\n');
        finished = true;
        res.end();
        return;
      }

      // 层0：读 session_id，与当前 active 不一致则 switch_session
      const reqSessionId = typeof parsed.session_id === 'string' && parsed.session_id.trim()
        ? parsed.session_id.trim() : '';
      if (reqSessionId && reqSessionId !== rpc.sessionId) {
        const sessionPath = resolve(SESSIONS_DIR, userId, reqSessionId + '.jsonl');
        if (sessionPath.startsWith(resolve(SESSIONS_DIR, userId)) && existsSync(sessionPath)) {
          try {
            const sw = await rpc.send('switch_session', { sessionPath });
            // M3：cancelled 在 resp.data（rpc-commands.md:602；原读 resp.cancelled 恒 undefined）
            if (!sw?.data?.cancelled) rpc.sessionId = reqSessionId;
          } catch {}
        }
      }

      // 层0：session_info 返回真实会话 id
      // M3 T-S3 修正：sessionId 在 resp.data.sessionId（rpc-commands.md:177；原读 resp.sessionId
      // 恒 undefined → session_info 一直返回 userId fallback → 前端 session_id 传错位 → ctx 错位）
      let realSessionId = rpc.sessionId;
      try { const state = await rpc.send('get_state'); realSessionId = state?.data?.sessionId || rpc.sessionId; } catch {}
      rpc.sessionId = realSessionId;

      // M3 T-S2：ctx.json 挪到 get_state 之后写——key 优先 realSessionId（extension 候选第一位），
      // 并同时写 legacy key（fresh spawn 会话未建时 realSessionId 仍为 userId fallback，
      // 此时靠 'default' key + extension 候选兜底；首轮必中）
      const ctxDir = resolve(SESSIONS_DIR, userId);
      const ctxBody = JSON.stringify({
        series_key: seriesKey, scope, user_id: userId,
        // P0 链路焊死（2026-10-26）：eval 批次标识随 ctx 传到 extension，逐行落轨迹——
        // runner 按 evalRunId+userId 取 verdict，不再依赖 sessionId（断供曾致整批误判）
        eval_run_id: typeof parsed.eval_run_id === 'string' ? parsed.eval_run_id : '',
        eval_task_id: typeof parsed.eval_task_id === 'string' ? parsed.eval_task_id : '',
        eval_repeat: Number.isInteger(parsed.eval_repeat) ? parsed.eval_repeat : 1,
        ts: new Date().toISOString(),
      });
      const legacyKey = (reqSessionId && reqSessionId !== userId) ? reqSessionId : 'default';
      const ctxKeys = new Set([legacyKey]);
      if (realSessionId && realSessionId !== userId && realSessionId !== legacyKey) ctxKeys.add(realSessionId);
      try {
        mkdirSync(ctxDir, { recursive: true });
        for (const k of ctxKeys) writeFileSync(resolve(ctxDir, k + '.ctx.json'), ctxBody);
      } catch (e) { console.error('[pi_gateway] ctx.json 写入失败:', e.message); }

      res.write(JSON.stringify({
        type: 'session_info',
        data: { session_id: realSessionId, user_id: userId },
      }) + '\n');

      // Block B：一次性消费用户中止标记——同会话（会话解析已完成，rpc.sessionId 为准）
      // 下一轮 prompt 尾部附系统注记；跨会话/无标记原样。被中止轮的部分产出仍留在
      // pi 会话历史（abort 只取消在途轮），不提醒则下一轮自然引用（multi-12 实证）。
      // 消费语义=一次性：标记随本轮清空；若下一问落在别的会话（如 new_session 回访轮），
      // 标记被消费但不注记、此后回原会话也不再补——简单可预期（审查 P2-7 设计取舍留痕）。
      abortFlagSession = rpc.pendingAbortNote;
      rpc.pendingAbortNote = null;
      const promptOut = withAbortNote(promptMessage, abortFlagSession, rpc.sessionId);

      // 发 prompt
      await rpc.send('prompt', { message: promptOut });

      // 读事件流直到 agent_settled（且验证器 pass/exhausted，非 retry 待发）/ error / aborted
      // P1-6 修复：验证器 fail 会 appendCustomMessageEntry 触发 pi 开 retry 轮，
      //   不能在首个 agent_settled 就 break，否则 retry 后的改进回复对客户端不可见
      // S7-c：残渣 settled 防线——本流零内容（thinking/text/tool）前到达的 settled
      // 只能是上一轮（尤其中止轮）的尾随事件，跳过不 break；连续两个零内容 settled
      // 才放弃（防真空轮挂到 300s 超时）。真轮必先产出内容再 settle。
      let sawContent = false;
      let staleSettled = 0;
      while (!rpc.disposed) {
        let event;
        if (staleSettled >= 1) {
          // S8 P0-3：已放过一个零内容 settled（按残渣 skip）——此后若无更多事件，
          // 读循环会永久挂在 nextEvent、锁死用户。挂 20s 无活动保险：停轮+收尾。
          event = await Promise.race([
            rpc.nextEvent(),
            new Promise(r => setTimeout(r, 20000, null)),
          ]);
          if (!event) {
            try { await rpc.abort(); } catch {}
            rpc.abortPending = false;   // S8-P1-1fix：内部 abort 不带用户意图，勿杀下一轮
            res.write(JSON.stringify({ type: 'error', data: { message: '响应中断（20s 无事件），本轮已中止，请重试' } }) + '\n');
            break;
          }
        } else {
          event = await rpc.nextEvent();
        }
        if (!event) break;   // S8 P1-3：dispose/exit 以无参唤醒 waiter → undefined → 防读 .type 崩
        // M3 T-S3：settled 时会话必已建立——刷新 realSessionId（fresh spawn 首轮 prompt 前
        // get_state 可能未返 sessionId），确保 mapEvent 读对 verdict 路径（修雷 1）
        if (event.type === 'agent_settled') {
          try { const st = await rpc.send('get_state'); if (st?.data?.sessionId) realSessionId = st.data.sessionId; } catch {}
        }
        const mapped = mapEvent(event, userId, realSessionId);
        // S7-c 收紧：只有 thinking/text 算"真轮已开始"——尾随 tool 事件不算
        //（abort_race3 实测：旧轮 tool_call 泄入会把防线点亮）
        if (mapped && ['thinking_delta', 'text_delta'].includes(mapped.type)) sawContent = true;
        if (mapped && mapped.type === 'settled' && !sawContent) {
          staleSettled++;
          if (staleSettled >= 2) {
            // S8 P0-3：连续两个零内容 settled——异常轮。必须先停 pi：否则 finally 清队+删锁后
            // 旧轮事件继续入队，级联泄入下一轮且下一轮无 lastAbortAt 余波保护。
            try { await rpc.abort(); } catch {}
            rpc.abortPending = false;   // S8-P1-1fix：同上
            res.write(JSON.stringify({ type: 'error', data: { message: '会话状态异常（连续空轮），本轮已重置，请重试' } }) + '\n');
            break;
          }
          continue;                        // 单个：视为残渣，继续等真轮事件（有 20s 保险）
        }
        if (mapped) res.write(JSON.stringify(mapped) + '\n');
        if (mapped && mapped.type === 'error') break;
        if (mapped && mapped.type === 'settled') {
          // verdict.pass=true 或 exhausted（无 retry）才 break；fail 但有 retry 继续读
          const vd = mapped.verdict;
          const pass = vd?.verdict === 'pass';
          const exhausted = vd && vd.verdict === 'fail' && !vd.can_continue;
          // 简化：fail 时 pi 会自动 retry，继续读直到下次 settled 或流关闭
          if (pass || exhausted || !vd) break;
          // fail 且有 retry → 不 break，继续读 retry 轮事件
        }
        if (event.type === 'aborted') { rpc.abortPending = false; break; }   // S8-P1-1fix：消费即清，防残留杀下一轮
      }
      finished = true;
      res.end();
    } catch (e) {
      console.error(`[pi_gateway] chat error:`, e.message);
      // Block B：防御性归还中止标记。注：catch 覆盖整个 try（含 prompt 已发出之后的流读错）——
      // 那种情况注记已随 prompt 入 pi 历史，归还只会让下一轮多附一次（新 user 消息、逐条剥离，冗余无害）。
      // rpc.disposed 时标记随对象丢弃（审查 P2-6 注释校正：原"本轮未成立"表述以偏概全）。
      if (abortFlagSession && rpc && !rpc.disposed) rpc.pendingAbortNote = abortFlagSession;
      try {
        // P1#11：不泄露内部信息，固定文案
        res.write(JSON.stringify({ type: 'error', data: { message: '对话处理出错，请重试' } }) + '\n');
      } catch {}
      finished = true;
      try { res.end(); } catch {}
    } finally {
      // 中止键 change（G1/D5）：先清迟到事件（abort/settled break 后 pi 仍可能吐尾事件，
      // 残留 eventQueue 会被下一轮 /chat 的 nextEvent 立即取走=泄入新流），再删锁。
      // JS 单线程下 drain→delete 间无交错；drain 时本请求已 break 无 waiter。
      if (rpc) rpc.eventQueue.length = 0;
      // P1#1：只在自己设过锁时才删
      if (lockSet) inflightLocks.delete(userId);
    }
    return;
  }

  // POST /abort — 中止键与单一在途轮次（2026-10-12）
  // 幂等：无在途/无 rpc → {ok, aborted:false}；有 → RpcClient.abort()
  // （本地推 aborted 唤醒 /chat 读循环 P1#4 + 发 RPC abort 到 pi 本体——
  //  extension 回灌自驱动，断网关流停不住，必须 pi 进程收到 abort）
  if (url.pathname === '/abort' && req.method === 'POST') {
    const body = await readBody(req);
    let parsed;
    try { parsed = JSON.parse(body); } catch { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid json' })); return; }
    const userId = validateUserId(parsed.user_id || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    const rpcForAbort = pool.get(userId);
    if (!rpcForAbort || rpcForAbort.disposed || !inflightLocks.has(userId)) {
      // Block B：幂等分支同样落用户中止标记——按下中止即"取消上一轮"，与在途真中止同
      // 语义。eval runner 在流收尾后才调 /chat/abort（streamChat 读到 done 才返回），
      // 实跑走的就是本分支；生产点击竞态（流刚结束才送达）亦然。无 rpc=从未对话，无
      // "上一轮"可标记。
      if (rpcForAbort && !rpcForAbort.disposed) rpcForAbort.pendingAbortNote = rpcForAbort.sessionId;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, aborted: false }));
      return;
    }
    try {
      await rpcForAbort.abort();
      // Block B：真中止路径落标记（/chat 消费时比对会话，跨会话不注记）。
      // 内部 abort（断连/20s 无事件/连续空轮）不落此标记——那三轮本就零内容无残留。
      rpcForAbort.pendingAbortNote = rpcForAbort.sessionId;
      // 竞态修复（2026-10-12 abort_race 实测）：中止轮的尾随 agent_settled 会在数百 ms 后
      // 到达——若新 /chat 已开读会被误当新轮 settled（新问题空转结束）。此处等它落完并排干：
      // 最多 2s×500ms 切片排干，见 settled 类事件提前收工。前端拿到本响应才解锁重发，竞态闭合。
      for (let i = 0; i < 4; i++) {
        await new Promise(r => setTimeout(r, 500));
        // S7-a：锁被新 /chat 接管 → 停止排干（队列事件归新流，偷走即丢事件）
        if (inflightLocks.has(userId)) break;
        let sawSettled = false;
        while (rpcForAbort.eventQueue.length > 0) {
          const ev = rpcForAbort.eventQueue.shift();
          if (ev && ev.type === 'agent_settled') sawSettled = true;   // S8 P2-3：队列存原始事件，'settled' 是映射后类型（死条件已删）
        }
        if (sawSettled) break;
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, aborted: true }));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
    return;
  }

  // GET /session?user_id= — 列表返 sessionFile + id 统一
  if (url.pathname === '/session' && req.method === 'GET') {
    const userId = validateUserId(url.searchParams.get('user_id') || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    try {
      const { readdirSync, statSync } = await import('node:fs');
      const userDir = resolve(SESSIONS_DIR, userId);
      const files = readdirSync(userDir).filter(f => f.endsWith('.jsonl'));
      const names = loadSessionNames(userId);
      const sessions = [];
      for (const f of files) {
        const stat = statSync(resolve(userDir, f));
        const id = f.replace('.jsonl', '');
        // B4：custom_name 来自 names.json sidecar（前端标题 = custom_name || name || id）
        sessions.push({ id, sessionFile: f, name: names[id] || id, custom_name: names[id], lastActivity: stat.mtime });
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ sessions }));
    } catch {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ sessions: [] }));
    }
    return;
  }

  // POST /session（新建会话——发 new_session RPC 命令）
  if (url.pathname === '/session' && req.method === 'POST') {
    const body = await readBody(req);
    let parsed;
    try { parsed = JSON.parse(body); } catch { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid json' })); return; }
    const userId = validateUserId(parsed.user_id || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    // 审查P0-1 配套：在途对话时建新会话会切走活跃会话（new_session 作用于 RPC 客户端当前进程）
    // → 破坏在途流。忙时 409（前端 onNewSession 失败回落 undefined 由 session_info 回填兜底）。
    if (inflightLocks.has(userId)) {
      res.writeHead(409, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: '上一请求进行中，稍后再试' }));
      return;
    }
    try {
      const rpc = getOrCreateRpc(userId);
      const resp = await rpc.send('new_session');
      // M3：new_session 响应 data 只有 {cancelled}（rpc-commands.md:144）——真实 id 须再查
      // get_state（原读 resp.sessionId 恒 'unknown'）
      let sessionId = 'unknown';
      try { const st = await rpc.send('get_state'); sessionId = st?.data?.sessionId || 'unknown'; } catch {}
      if (parsed.title) {
        try { await rpc.send('set_session_name', { name: parsed.title }); } catch {}
        // B4：镜像进 names.json sidecar（列表显示走 sidecar 单一真值）
        try {
          if (sessionId && sessionId !== 'unknown') {
            const names = loadSessionNames(userId);
            names[sessionId] = parsed.title;
            saveSessionNames(userId, names);
          }
        } catch {}
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ session_id: sessionId, title: parsed.title || sessionId }));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: '创建会话失败，请重试' }));
    }
    return;
  }

  // POST /session/rename — B4：{user_id, session_id, name} → names.json sidecar
  if (url.pathname === '/session/rename' && req.method === 'POST') {
    const body = await readBody(req);
    let parsed;
    try { parsed = JSON.parse(body); } catch { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid json' })); return; }
    const userId = validateUserId(parsed.user_id || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    const sessionId = typeof parsed.session_id === 'string' ? parsed.session_id.trim() : '';
    const name = typeof parsed.name === 'string' ? parsed.name.trim().slice(0, 60) : '';
    if (!sessionId || !name) { res.writeHead(400); res.end(JSON.stringify({ error: 'session_id and name required' })); return; }
    // 必须对应真实会话文件（同时天然挡 ../ 路径注入）
    const userDir = resolve(SESSIONS_DIR, userId);
    const sessionFile = resolve(userDir, sessionId + '.jsonl');
    // 审查P2-1：前缀带分隔符，防 userId=default 时 ../defaultx 归一化后前缀撞名绕过
    if (!sessionFile.startsWith(userDir + sep) || !existsSync(sessionFile)) {
      res.writeHead(404); res.end(JSON.stringify({ error: 'session not found' })); return;
    }
    try {
      const names = loadSessionNames(userId);
      names[sessionId] = name;
      saveSessionNames(userId, names);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, session_id: sessionId, custom_name: name }));
    } catch {
      res.writeHead(500); res.end(JSON.stringify({ error: '写入失败' }));
    }
    return;
  }

  // DELETE /session/:id?user_id= — D2（2026-11-02）：删除会话文件与名称 sidecar
  if (url.pathname.startsWith('/session/') && req.method === 'DELETE') {
    const userId = validateUserId(url.searchParams.get('user_id') || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    const sessionId = decodeURIComponent(url.pathname.slice('/session/'.length)).trim();
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(sessionId)) {
      res.writeHead(400); res.end(JSON.stringify({ error: 'invalid session_id' })); return;
    }
    if (inflightLocks.has(userId)) {
      res.writeHead(409); res.end(JSON.stringify({ error: '上一请求进行中，稍后再试' })); return;
    }
    const userDir = resolve(SESSIONS_DIR, userId);
    const sessionFile = resolve(userDir, sessionId + '.jsonl');
    if (!sessionFile.startsWith(userDir + sep) || !existsSync(sessionFile)) {
      res.writeHead(404); res.end(JSON.stringify({ error: 'session not found' })); return;
    }
    try {
      unlinkSync(sessionFile);
      try {
        const names = loadSessionNames(userId);
        if (names[sessionId]) { delete names[sessionId]; saveSessionNames(userId, names); }
      } catch {}
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, session_id: sessionId }));
    } catch {
      res.writeHead(500); res.end(JSON.stringify({ error: '删除失败' }));
    }
    return;
  }

  // GET /session/messages?user_id=&session_id= — 会话历史回显（change:会话历史与对话侧完善）
  // D1：switch_session(目标文件) → RPC get_messages（作用于当前活跃会话）→ 同步 rpc.sessionId。
  // Gap6 + 审查P2-1：sessionPath 必须落在 SESSIONS_DIR/{userId}/ 内（前缀带分隔符防 default→defaultx 撞名绕过）。
  // Gap1 + 审查P1-2：本端点会改写用户 RPC 进程的活跃会话——全程持有 per-user 锁
  //（与 /chat 同一把 inflightLocks：互斥在途对话/并发的同类请求，忙时 409 固定文案）。
  if (url.pathname === '/session/messages' && req.method === 'GET') {
    const userId = validateUserId(url.searchParams.get('user_id') || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    const reqSessionId = (url.searchParams.get('session_id') || '').trim();
    if (!reqSessionId) { res.writeHead(400); res.end(JSON.stringify({ error: 'session_id required' })); return; }

    const userDir = resolve(SESSIONS_DIR, userId);
    const sessionPath = resolve(userDir, reqSessionId + '.jsonl');
    if (!sessionPath.startsWith(userDir + sep) || !existsSync(sessionPath)) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'session not found' }));
      return;
    }

    if (inflightLocks.has(userId)) {
      res.writeHead(409, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: '上一请求进行中，稍后再试' }));
      return;
    }
    inflightLocks.set(userId, true);
    let msgLockSet = true;
    try {
      const rpc = getOrCreateRpc(userId);
      const sw = await rpc.send('switch_session', { sessionPath });
      // cancelled 在 resp.data（rpc.md switch_session：extension session_before_switch 可取消；
      // /chat L527 同款读法）。取消/失败 → 502 固定文案，不泄内部信息。
      if (sw?.success === false || sw?.data?.cancelled) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: '获取会话历史失败，请重试' }));
        return;
      }
      rpc.sessionId = reqSessionId;
      const resp = await rpc.send('get_messages');
      const messages = resp?.data?.messages;
      if (!Array.isArray(messages)) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: '获取会话历史失败，请重试' }));
        return;
      }
      // 真实 sessionId 优先（get_state 的 resp.data.sessionId，/chat L537 同款），沿用请求 id 兜底
      let sessionId = reqSessionId;
      try { const st = await rpc.send('get_state'); if (st?.data?.sessionId) sessionId = st.data.sessionId; } catch {}
      rpc.sessionId = sessionId;
      // Block B：剥离网关注入的中止注记——内部标记不进前端历史回显（与 ChatView D4
      // 前缀过滤契约同向；注记只服务模型上下文，原始文件保留供审计）
      const shown = stripAbortNoteFromMessages(messages);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ session_id: sessionId, messages: shown }));
    } catch (e) {
      console.error('[pi_gateway] session/messages error:', e.message);
      // P1#11 同款：不泄内部信息；res.end 抛错（客户端已断）时 headersSent 兜底防 double writeHead
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: '获取会话历史失败，请重试' }));
      } else {
        try { res.end(); } catch {}
      }
    } finally {
      if (msgLockSet) inflightLocks.delete(userId);
    }
    return;
  }

  // B3：POST /ui-response（前端回填 extension_ui_response）
  if (url.pathname === '/ui-response' && req.method === 'POST') {
    const body = await readBody(req);
    let parsed;
    try { parsed = JSON.parse(body); } catch { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid json' })); return; }
    const userId = validateUserId(parsed.user_id || 'default');
    if (!userId) { res.writeHead(400); res.end(JSON.stringify({ error: 'invalid user_id' })); return; }
    const rpc = pool.get(userId);
    if (!rpc || rpc.disposed) { res.writeHead(404); res.end(JSON.stringify({ error: 'no active session' })); return; }
    try {
      await rpc.respondUi(parsed.id, parsed.value, parsed.cancelled || false);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: '回填失败' }));
    }
    return;
  }

  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: `not found: ${url.pathname}` }));
});

function readBody(req, maxLen = 1_000_000) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on('data', (c) => {
      total += c.length;
      if (total > maxLen) { req.destroy(); reject(new Error('body too large')); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    req.on('error', reject);
  });
}

// 2026-10-19 收口：显式绑 127.0.0.1（原缺省=all-interfaces，与"浏览器只达8002"的单门设计不符）
server.listen(PORT, '127.0.0.1', () => {
  console.error(`[pi_gateway] listening on http://127.0.0.1:${PORT}`);
  console.error(`[pi_gateway] pi=${PI_BIN} model=deepseek-v4-flash`);
  console.error(`[pi_gateway] sessions=${SESSIONS_DIR}`);
  // P1-3：可选预热——PRISM_WARM_USER 指定时，启动即预 spawn 该用户进程，避免其首次吃冷启动
  const warmUser = process.env.PRISM_WARM_USER;
  if (warmUser && validateUserId(warmUser)) {
    try {
      getOrCreateRpc(warmUser);
      console.error(`[pi_gateway] warm pool 预热用户 ${warmUser}`);
    } catch (e) {
      console.error(`[pi_gateway] warm pool 预热失败: ${e.message}`);
    }
  }
});
