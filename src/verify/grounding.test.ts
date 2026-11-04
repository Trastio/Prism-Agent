/**
 * T-2.2.5 单测 · tool_result grounding（数值 + 名称 8 错误测试集）
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx src/verify/grounding.test.ts
 *
 * 覆盖：
 * - 8 名称错误测试集全拦截（探索型→探索版 / 启航型→公务版 / ...）
 * - 数值容差 ±2%（verifyNumbers）
 * - collectNameTruth 提取
 * - 名称正确通过 / 综合 groundResult
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  extractNumbers,
  verifyNumbers,
  verifyNames,
  collectNameTruth,
  groundResult,
} from './grounding.ts';

describe('verifyNumbers · 数值容差 ±2%', () => {
  it('容差内通过（4450 vs 4436，差 0.3%）', () => {
    const r = verifyNumbers('8月销量4450台', [4436]);
    assert.equal(r.pass, true);
    assert.equal(r.mismatches.length, 0);
  });

  it('容差边界通过（4436±2%=88.72，4524 仍在内）', () => {
    const r = verifyNumbers('8月销量4524台', [4436]);
    assert.equal(r.pass, true);
  });

  it('超容差失败（10774 vs 4436）', () => {
    const r = verifyNumbers('8月销量10774台', [4436]);
    assert.equal(r.pass, false);
    assert.ok(r.mismatches.length > 0);
  });

  it('模型回复多出工具未返回的大数值 → 失败', () => {
    const r = verifyNumbers('销量4436台，累计1.2万辆', [4436]);
    assert.equal(r.pass, false);
    assert.ok(r.mismatches.some(m => /工具未返回/.test(m)));
  });

  it('带"万/亿"单位提取（1.2万=12000）', () => {
    const nums = extractNumbers('累计约1.2万辆');
    assert.ok(nums.some(n => n.value === 12000));
  });
});

describe('collectNameTruth · 名称真值集提取', () => {
  it('从 toolResults 提取 series/brand/model_name 等字段', () => {
    const truth = collectNameTruth([
      { series: '银河E5', model_name: '26款 530Km 探索版', brand: '吉利银河' },
      { series_name: '银河E5', tag_category: '舒适' },
      { manufacturer: '广汽丰田', irrelevant: 'noise' },
    ]);
    assert.ok(truth.has('银河E5'));
    assert.ok(truth.has('26款 530Km 探索版'));
    assert.ok(truth.has('吉利银河'));
    assert.ok(truth.has('广汽丰田'));
    assert.ok(truth.has('舒适'));
    // 非名称字段不进真值集
    assert.ok(!truth.has('noise'));
  });

  it('空数组返回空集', () => {
    const truth = collectNameTruth([]);
    assert.equal(truth.size, 0);
  });
});

describe('verifyNames · 8 名称错误测试集全拦截', () => {
  const cases: Array<[string, string[], string]> = [
    ['26款 530Km 探索型', ['26款 530Km 探索版'], '探索型→探索版'],
    ['530km 启航型', ['530km 公务版'], '启航型→公务版'],
    ['全域精灵版', ['全球精灵版'], '全域精灵版→全球精灵版'],
    ['铂智7 是 SUV', ['三厢轿车'], '铂智7 SUV→三厢轿车'],
    ['星纪元 ET 08 EV', ['比亚迪 海豹08 EV'], '星纪元ET08→比亚迪海豹08'],
    ['蔚来 Z9 GT', ['腾势 Z9 GT'], '蔚来Z9→腾势Z9'],
    ['智驾版', ['激光雷达版'], '智驾版→激光雷达版'],
    ['一汽丰田 GAC', ['广汽丰田'], '一汽丰田GAC→广汽丰田'],
  ];

  for (const [modelText, truth, label] of cases) {
    it(`${label} 应被拦截（pass=false）`, () => {
      const r = verifyNames(modelText, new Set(truth));
      assert.equal(r.pass, false, `${label} 未被拦截，mismatches: ${r.mismatches.join('; ')}`);
      assert.ok(r.mismatches.length > 0);
    });
  }
});

describe('verifyNames · 正向用例', () => {
  it('名称与真值一致 → 通过', () => {
    const r = verifyNames('26款 530Km 探索版', new Set(['26款 530Km 探索版']));
    assert.equal(r.pass, true);
  });

  it('版型名是真值子串（探索版 in 26款 530Km 探索版）→ 通过', () => {
    const r = verifyNames('探索版', new Set(['26款 530Km 探索版']));
    assert.equal(r.pass, true);
  });
});

describe('verifyNames · R1 前缀放行（2026-10-11 风云T7 实案）', () => {
  it('纯 CJK 前缀 + 余部非 CJK（风云→风云T7）→ 放行', () => {
    const r = verifyNames('风云T7 舆情负面 23 帖', new Set(['风云T7', '空间', '舒适']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('品牌简称前缀（银河→银河E5）→ 放行', () => {
    const r = verifyNames('银河E5 和星愿对比', new Set(['银河E5', '星愿']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('token 恰等于真值名（走精确命中，不进前缀分支）→ 通过', () => {
    const r = verifyNames('风云T7', new Set(['风云T7', '空间']));
    assert.equal(r.pass, true);
  });

  it('余部以符号开头的变体名（风云 → 风云-PRO）→ 前缀放行', () => {
    const r = verifyNames('风云-PRO 上市', new Set(['风云-PRO']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('非前缀 CJK 词仍走原逻辑（蔚来 Z9 vs 腾势 Z9 GT → 拦截，防张冠李戴回归）', () => {
    const r = verifyNames('蔚来 Z9 GT', new Set(['腾势 Z9 GT']));
    assert.equal(r.pass, false);
  });

  it('余部为 CJK 的前缀不放行（探索型→探索版 仍由后缀逻辑拦截）', () => {
    const r = verifyNames('探索型', new Set(['26款 530Km 探索版']));
    assert.equal(r.pass, false);
  });
});

describe('verifyNames · C1 通用域白名单（2026-10-14 R1-deep 普通词误报）', () => {
  it('"银河E5 销量如何"式句子零误报', () => {
    const r = verifyNames('银河E5 销量如何', new Set(['银河E5']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('顿号罗列普通词 vs 2 字维度真值（archive 实案形态）→ 不误报人工转写', () => {
    const r = verifyNames('销量、口碑、配置三个维度均有数据，空间口碑最好', new Set(['电耗', '空间']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('舆情散文罗列（价格/性价比/续航 vs 电耗）→ 不误报', () => {
    const r = verifyNames('风云T7 舆情：价格偏高、性价比一般，续航口碑分化', new Set(['风云T7', '电耗']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('纯泛域短语句（白名单词+单字连词）不触发张冠李戴兜底', () => {
    const r = verifyNames('外观、内饰、空间、舒适与价格对比分析', new Set(['电耗', '续航']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  // 已知残留（留下一轮，与 archive"不到"同类）：无实体且含白名单外语的散文
  // （如"驾驶体验为主"）仍会触发张冠李戴兜底——超出 20 词白名单授权范围，
  // 实体句（conclusion_text 实际形态）不受影响。

  it('带实体+泛域词混合（市场保有量低，售后服务网点少）→ 通过', () => {
    const r = verifyNames('风云T7 市场保有量低，售后服务网点少', new Set(['风云T7', '电耗']));
    assert.equal(r.pass, true, `mismatches: ${r.mismatches.join('; ')}`);
  });

  it('白名单不放行张冠李戴（蔚来 Z9 GT vs 腾势 Z9 GT 仍拦，8 case 精神）', () => {
    const r = verifyNames('蔚来Z9 GT 销量如何', new Set(['腾势 Z9 GT']));
    assert.equal(r.pass, false);
  });

  it('残部 >1 字的非泛域词不放行（保时捷911 编造型）', () => {
    // "保时捷" 剥白名单后残部 3 字 → 仍走身份词逻辑，无真值匹配 → 兜底拦截
    const r = verifyNames('保时捷911 配置分析', new Set(['银河E5']));
    assert.equal(r.pass, false, `mismatches: ${r.mismatches.join('; ')}`);
  });
});

describe('groundResult · 综合 grounding（数值+名称）', () => {
  it('数值+名称均通过 → 综合通过', () => {
    const r = groundResult(
      '银河E5 八月销量4436台，座椅材质仿皮',
      [4436],
      [{ series: '银河E5', model_name: '26款 530Km 探索版' }]
    );
    assert.equal(r.pass, true);
    assert.equal(r.number_check.pass, true);
    assert.equal(r.name_check.pass, true);
  });

  it('名称错误 → 综合 fail（数值对也不救）', () => {
    const r = groundResult(
      '银河E5 八月销量4436台，530Km 探索型',
      [4436],
      [{ series: '银河E5', model_name: '26款 530Km 探索版' }]
    );
    assert.equal(r.pass, false);
    assert.equal(r.name_check.pass, false);
  });
});
