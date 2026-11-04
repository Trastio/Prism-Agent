/**
 * Prism-Agent · 完成验证器（T-2.3.2）
 *
 * agent_settled 事件插验收（官方名非 agent_before_settle）。
 * CLAIM/VERIFY 汽车场景化（spec §2.3.2）：
 * - CLAIM：结论必须有 conclusion_text + supported_by(行ID) + as_of + scope
 * - VERIFY：行ID 真实存在 / as_of 一致 / 越界检查 / 数据缺口声明
 * - max 1 次 continuation 再不过 fail
 *
 * 阶段1 教训：
 * - 报告① v0.2 "市场侧印证舒适性" → 越界 fail
 * - 报告③ v0.2 无 supported_by → fail
 */

import { openAutohomeForTools } from '../tools/_shared.ts';

// ---------------------------------------------------------------------------
// CLAIM 结构（agent 必须产出）
// ---------------------------------------------------------------------------

export interface Claim {
  conclusion_text: string;
  supported_by: string[];      // 行 ID 列表，如 ['review_tags:7650/舒适/con', 'sales_trim:银河E5/2026-08/月末']
  as_of: string;               // 数据时点
  scope: '口碑内' | '配置内' | '市场侧不归因' | '跨维度';
  data_gaps_declared?: string[];  // 数据缺口声明（舆情未接入等）
}

export interface VerifyResult {
  pass: boolean;
  failures: string[];
  attempt: number;             // 1=首次, 2=continuation 后
  can_continue: boolean;       // attempt<2 时允许一次 continuation
}

// ---------------------------------------------------------------------------
// VERIFY 校验
// ---------------------------------------------------------------------------

/** 校验 supported_by 行 ID 真实存在
 *
 * 2026-10-08 单源化：直读 Prism 主库（prism-dashboards/data/autohome.db）。
 * 该路径不含中文，无 better-sqlite3 中文参数绑定 bug（原先走物化视图正是为绕开该 bug）。
 */
function verifySupportedBy(supported_by: string[]): string[] {
  const failures: string[] = [];
  const db = openAutohomeForTools();
  try {
    for (const ref of supported_by) {
      const m = ref.match(/^(\w+):(.+)$/);
      if (!m) {
        failures.push(`supported_by "${ref}" 格式错误（应为 table:key/value/...）`);
        continue;
      }
      const [, table, rest] = m;
      const parts = rest.split('/');
      const ok = checkRefExists(db, table, parts);
      if (!ok) {
        failures.push(`supported_by "${ref}" 库中无对应数据`);
      }
    }
  } finally {
    db.close();
  }
  return failures;
}

/** 在 Prism 主库校验原表行是否存在（键/语义与物化视图一致） */
function checkRefExists(db: import('better-sqlite3').Database, table: string, parts: string[]): boolean {
  try {
    switch (table) {
      case 'review_tags':
      case 'mv_reviews_dim': {
        // model_id/tag_category(/sentiment)
        if (parts.length < 2) return false;
        const r = db
          .prepare('SELECT 1 FROM review_tags WHERE CAST(model_id AS TEXT)=? AND tag_category=? LIMIT 1')
          .get(String(parts[0]), parts[1]);
        return !!r;
      }
      case 'sales_trim':
      case 'mv_sales_monthly': {
        // series/year(/month)
        if (parts.length < 2) return false;
        const r = db
          .prepare('SELECT 1 FROM sales_trim WHERE series=? AND year=? LIMIT 1')
          .get(parts[0], Number(parts[1]));
        return !!r;
      }
      case 'config_snapshots':
      case 'mv_config_spec': {
        // series_id(/spec_id)
        if (parts.length < 1) return false;
        const r = db
          .prepare('SELECT 1 FROM config_snapshots WHERE series_id=? LIMIT 1')
          .get(Number(parts[0]));
        return !!r;
      }
      default:
        return false;
    }
  } catch {
    return false;
  }
}

/** 越界检查：内容组合判定（不读 claim.scope，修跨维度免检）
 * 块1.1：市场侧↔产品力互为归因 = 越界
 * 三层共用 NEG_RE（验证层/runner/提示词示例）——词表形态必须与 eval/trap_check.mjs 保持同步
 * （Step8 审查 P1-1：v1.2 假阴实录句"不把销量下滑归因到产品力"曾只在 eval 侧豁免、本层漏"不把"形态，
 *  活闸照样 verdict fail 封 1 分——三层同改是硬纪律，completion.test 有"不把"句回归锁） */
export const NEG_RE = /(不能|无法|不足以|谈不上|并不|不应|难以|不应据此|不能据此|不可|无关|没有关系|非因果|不得归因|不构成|不支撑|不佐证|不归因|不作归因|不做归因|无需归因|不将[^。\n]{0,8}归因|不把[^。\n]{0,8}归因|不对[^。\n]{0,10}(做|进行)[^。\n]{0,4}归因)/;
const MARKET_RE = /(销量|市场|同比|环比|市占率|交付量|上险量)/;
const PRODUCT_RE = /(配置|舒适|隔音|座椅|空间|续航|智能化|智驾|车机|轮毂)/;
const ATTRIB_RE = /(印证|佐证|支撑|归因|导致|说明|反映|体现|所致)/;

function verifyScope(claim: Claim): string[] {
  const failures: string[] = [];
  const text = claim.conclusion_text;

  // 内容组合判定（不依赖 claim.scope）
  if (MARKET_RE.test(text) && PRODUCT_RE.test(text) && ATTRIB_RE.test(text)) {
    // 项11：对齐规格——逐词判定，任一归因词无否定语境即 fail（不再"一否全放"）
    // Step8 P1-1（深修）：窗口延伸至含被检词本身——"不把X归因/不将X归因/不对X做归因"这类
    // 否定短语的词尾就是被检词，只看前 14 字永远拼不完整（曾致该类豁免形态在本层是死代码，
    // v1.2 cross-02 实录句被判越界假阴）。真违规句（无否定语境）不受影响。
    const hits = [...text.matchAll(new RegExp(ATTRIB_RE.source, 'g'))];
    const hasViolation = hits.some(m => {
      const i = m.index ?? 0;
      const before = text.slice(Math.max(0, i - 14), i + m[0].length);
      return !NEG_RE.test(before);
    });
    if (hasViolation) {
      failures.push('市场侧与产品力互为归因（越界：市场侧数据不归因产品力）');
    }
  }

  return failures;
}

/** 数据缺口声明检查 */
function verifyDataGaps(claim: Claim, identity_coverage?: unknown): string[] {
  const failures: string[] = [];
  // 若对象覆盖率不全（如铂智7X），必须有 data_gaps_declared
  if (identity_coverage && typeof identity_coverage === 'object') {
    const cov = identity_coverage as Record<string, { hit: boolean }>;
    const missing = Object.entries(cov)
      .filter(([, v]) => !v.hit)
      .map(([k]) => k);
    if (missing.length > 0 && (!claim.data_gaps_declared || claim.data_gaps_declared.length === 0)) {
      failures.push(`数据缺口未声明：${missing.join(', ')} 维度缺失但未在 data_gaps_declared 中声明`);
    }
  }
  return failures;
}

// ---------------------------------------------------------------------------
// 主入口
// ---------------------------------------------------------------------------

const attemptMap = new Map<string, number>();  // session_id → attempt count

/** M1 运行时约束（2026-10-07 实测）：pi.exe 为 Bun 编译，进程内 better-sqlite3 触发
 * NAPI FATAL panic → **extension 运行时禁止查库**。故四件套拆两层：
 * - verifyClaimShape：纯逻辑（完整性/越界/缺口），extension 与 Node 通用
 * - verifySupportedBy：行ID查库，仅 Node 单测/verifyCompletion 用；extension 侧走
 *   FastAPI POST /verify/claim（服务端真值校验，Python sqlite3 无此坑）
 */

/** D7 纯函数·形状层：CLAIM 完整性 + 越界 + 缺口声明（无 DB 依赖，任何运行时可调） */
export function verifyClaimShape(
  claim: Claim,
  identity_coverage?: unknown
): { pass: boolean; failures: string[] } {
  const failures: string[] = [];
  try {
    // CLAIM 完整性
    if (!claim.conclusion_text) failures.push('缺少 conclusion_text');
    if (!claim.supported_by || claim.supported_by.length === 0) failures.push('缺少 supported_by 行 ID');
    if (!claim.as_of) failures.push('缺少 as_of 数据时点');
    if (!claim.scope) failures.push('缺少 scope 结论范围');

    // VERIFY：越界检查
    failures.push(...verifyScope(claim));

    // VERIFY：数据缺口声明
    failures.push(...verifyDataGaps(claim, identity_coverage));
  } catch (e) {
    failures.push(`verifyCompletion 内部异常: ${(e as Error).message}`);
  }
  return { pass: failures.length === 0, failures };
}

/** D7 纯函数·全量（形状 + 行ID查库）——仅 Node 运行时（单测）使用 */
export function verifyClaimChecks(
  claim: Claim,
  identity_coverage?: unknown
): { pass: boolean; failures: string[] } {
  const shape = verifyClaimShape(claim, identity_coverage);
  const failures = [...shape.failures];
  try {
    if (claim.supported_by?.length > 0) {
      failures.push(...verifySupportedBy(claim.supported_by));
    }
  } catch (e) {
    failures.push(`verifyCompletion 内部异常: ${(e as Error).message}`);
  }
  return { pass: failures.length === 0, failures };
}

export function verifyCompletion(
  sessionId: string,
  claim: Claim,
  identity_coverage?: unknown
): VerifyResult {
  const attempt = (attemptMap.get(sessionId) ?? 0) + 1;
  attemptMap.set(sessionId, attempt);

  // D7：校验逻辑走纯函数；此处只管 attemptMap 生命周期（原 try/finally 清理语义保留，
  // 仅服务 mixed 分支——3.5 Gap6 定案，library/none 保底的 attempt 走 prism-verifier-state entry）
  const { pass, failures } = verifyClaimChecks(claim, identity_coverage);
  const can_continue = !pass && attempt < 2;
  if (pass || attempt >= 2) {
    attemptMap.delete(sessionId);
  }
  return { pass, failures, attempt, can_continue };
}
