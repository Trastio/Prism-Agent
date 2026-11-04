/** harness 登记收敛归档追加（2026-10-14）：car-reputation-research 两阶段协议的执行层状态门。
 * 红线#5 法治：skill 文本里的流程纪律（扫描→点名→深挖）模型会越权（实证：一轮跳完全部），
 * 本门把阶段约束变成系统开关——scanning 态锁深挖工具与模板 B 导出，被拦时返回可自纠的指引。
 * 状态存于 pi 进程内存（每用户一进程=天然隔离）；进程重启后态归 idle——深挖门重开属可接受降级
 * （门主要约束首轮边界，重启即新工作周期）。 */

export type WorkflowPhase = 'idle' | 'scanning' | 'named';

export const WORKFLOW_SKILL = 'car-reputation-research';
export const PHASE_ENTRY_TYPE = 'prism-skill-phase';
export const TEMPLATE_B_MARKER = '用户对照总览';

/** 深挖类工具：仅 named 态放行（scanning 态必须先出候选人名单交用户点名）。 */
export const DEEP_TOOLS = ['social_user_profile', 'social_user_posts'];

export interface GateResult {
  block: boolean;
  reason: string;
}

export function decideWorkflowGate(phase: WorkflowPhase, toolName: string, inputJson: string): GateResult {
  if (phase !== 'scanning') return { block: false, reason: '' };
  if (DEEP_TOOLS.includes(toolName)) {
    return {
      block: true,
      reason: '扫描阶段：深挖工具已锁。请先完成候选人名单（带信息密度评分，推荐 2-3 人并说明理由）交给用户点名；'
        + '用户点名后进入深挖轮，本工具自动解锁。若用户只要全网汇总，请用模板 A 交付（不含"用户对照总览"表）。',
    };
  }
  if (toolName === 'export_document' && inputJson.includes(TEMPLATE_B_MARKER)) {
    return {
      block: true,
      reason: '模板 B（含"用户对照总览"）需完成深挖轮后才能导出：被点名用户逐人 profile+posts 深挖、溯源清单齐备。'
        + '若本次只是全网反馈汇总，请改用模板 A（去掉"用户对照总览"表）。',
    };
  }
  return { block: false, reason: '' };
}

/** 阶段推进判据：before_agent_start 的新用户轮。回灌轮（验证器通知触发的轮）不推进。 */
export function shouldAdvancePhase(phase: WorkflowPhase, userPrompt: string | undefined, isRetryTurn: boolean): boolean {
  return phase === 'scanning' && !isRetryTurn;
}
