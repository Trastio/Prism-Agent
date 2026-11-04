/**
 * 块0.5 D-1：脱敏单一事实源（纯 TS，禁 node/DOM 依赖，只用正则字面量）
 * extension / 前端 tracker.ts / memory.json 三处共用，消除双实现
 */

/** VIN 17位（不含 I/O/Q） */
const VIN_RE = /[A-HJ-NPR-Z0-9]{17}/g;

/** 车牌（省+字母+5位） */
const PLATE_RE = /[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9]/g;

/** 脱敏：VIN/车牌 → *** */
export function sanitize(s: string): string {
  if (!s) return s;
  return s.replace(VIN_RE, '***').replace(PLATE_RE, '***');
}

/** 正则字符串（供跨语言 spec 共享） */
export const REDACTION_SPEC = {
  vin: '[A-HJ-NPR-Z0-9]{17}',
  plate: '[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9]',
};
