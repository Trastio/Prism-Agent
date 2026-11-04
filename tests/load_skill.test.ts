/**
 * load_skill 单测（社媒深挖能力包 M2）
 * 运行：node --test --import tsx tests/load_skill.test.ts
 * 覆盖：合法加载 SKILL.md / 引用文件加载 / 穿越拒绝（../、绝对路径、大写、盘符）/ 不存在
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readSkillFile } from '../.pi/extensions/prism-guardrails/skills.ts';

describe('load_skill 受限读取', () => {
  it('合法技能名：加载 SKILL.md（依赖 .pi/skills/car-reputation-research 已落盘）', () => {
    const r = readSkillFile('car-reputation-research');
    assert.ok(r.ok, r.reason);
    assert.match(r.text!, /画像输出限于人群理解颗粒度|铁律/);
    assert.ok(r.files!.some(f => f.includes('deliverable-spec')));
  });
  it('引用文件：references/deliverable-spec.md 可加载', () => {
    const r = readSkillFile('car-reputation-research', 'references/deliverable-spec.md');
    assert.ok(r.ok, r.reason);
    assert.match(r.text!, /模板/);
  });
  it('穿越拒绝：../、绝对路径、大写名、盘符', () => {
    assert.ok(!readSkillFile('../secrets').ok);
    assert.ok(!readSkillFile('car-reputation-research', '../../prism-api/.env').ok);
    assert.ok(!readSkillFile('Car-Reputation').ok);   // 大写 → NAME_RE 拒
    assert.ok(!readSkillFile('car-reputation-research', 'C:/Windows/win.ini').ok);
  });
  it('不存在：给出可加载文件清单', () => {
    const r = readSkillFile('car-reputation-research', 'references/nope.md');
    assert.ok(!r.ok);
    assert.match(r.reason!, /不存在/);
  });
});
