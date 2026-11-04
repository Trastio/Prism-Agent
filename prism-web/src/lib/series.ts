/** 车系状态辅助：最近车系列表（localStorage）
 * C2 修复：此前 Sidebar 只读不写，"最近车系"恒空——写入统一走这里。
 */

const KEY = 'prism_recent_series';
const CAP = 8;

export function getRecentSeries(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export function pushRecentSeries(name: string): void {
  if (!name.trim()) return;
  const list = getRecentSeries().filter((s) => s !== name);
  list.unshift(name);
  try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, CAP))); } catch { /* 隐私模式等写入失败：静默 */ }
}
