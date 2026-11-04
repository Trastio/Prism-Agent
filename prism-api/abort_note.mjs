/**
 * Block B（判分器修复与七题处置，2026-10-27）：用户中止轮残留注记——纯函数模块。
 *
 * 背景（multi-12 实证，v1.2 两跑 0 分）：/abort 只取消在途轮，被中止轮已流出的部分
 * 内容仍留在会话历史，下一轮 agent 视其为"上一轮"自然引用（t2 主动引用被中止 t1 的
 * 三车数字）。pi RPC 命令面（pi-windows-x64/docs/rpc.md §Commands）无会话注入命令
 * （prompt/steer/follow_up 均触发 agent 轮，get_entries 只读），故主案走工单认可的
 * "下一次请求附加上下文"：网关在 /abort 落一次性标记，/chat 同会话下一轮 prompt 尾部
 * 追加系统注记，/session/messages 历史回显时剥离（前端零泄漏——不借 VERIFIER 前缀：
 * 该前缀会误触 extension isVerifierRetryTurn(index.ts:806) 破坏出口闸 retry 语义）。
 *
 * 纯函数外置同 map_event.mjs 先例（pi_gateway.mjs import 即 listen，内联不可单测）。
 * 注：注记文案不得含车系名/数字——multi-12 trap_params.residue 词面会误伤判分。
 */

/** 注记标记（测试与 e2e 原始会话文件断言共用；改文案勿动标记头） */
export const ABORT_NOTE_MARK = '[Prism 系统注记]';

/** 追加到用户消息尾部的完整注记（含前导空行；append/strip 共用同一常量=单源） */
export const ABORT_NOTE = `\n\n${ABORT_NOTE_MARK} 上一轮回答已被用户中止，属于未完成交付的中间内容：其中的数字、结论与对比不应作为有效上下文引用。请仅围绕当前新问题独立查证作答，不要与被中止轮的内容作对比或延伸。`;

/**
 * 给出站 prompt 附加中止注记。
 * flagSessionId：/abort 时落下的被中止会话 id（null=无标记）；currentSessionId：本轮
 * /chat 解析后的会话。两者一致才附——中止残留只影响原会话，跨会话新问题不注记。
 */
export function withAbortNote(message, flagSessionId, currentSessionId) {
  if (!flagSessionId || flagSessionId !== currentSessionId) return message;
  return message + ABORT_NOTE;
}

/**
 * 历史回显剥离：user 消息 content（字符串或 blocks 形态）尾部若带注记则剥掉。
 * 网关内部标记不进前端（与 ChatView D4 前缀过滤契约同向）；assistant/其他角色不动。
 * 非数组入参原样返回（调用方 /session/messages 已先行 Array.isArray 校验）。
 */
export function stripAbortNoteFromMessages(messages) {
  if (!Array.isArray(messages)) return messages;
  return messages.map((m) => {
    if (!m || m.role !== 'user') return m;
    if (typeof m.content === 'string' && m.content.endsWith(ABORT_NOTE)) {
      return { ...m, content: m.content.slice(0, m.content.length - ABORT_NOTE.length) };
    }
    if (Array.isArray(m.content) && m.content.length > 0) {
      const last = m.content[m.content.length - 1];
      if (last && typeof last.text === 'string' && last.text.endsWith(ABORT_NOTE)) {
        const lastStripped = { ...last, text: last.text.slice(0, last.text.length - ABORT_NOTE.length) };
        return { ...m, content: [...m.content.slice(0, -1), lastStripped] };
      }
    }
    return m;
  });
}
