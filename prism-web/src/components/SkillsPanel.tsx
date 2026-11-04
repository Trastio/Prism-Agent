/**
 * 能力总览面板（原"SKILLS 库"，2026-10-12 用户纠偏重构：概念诚实化）
 *
 * 两层分类——skill ≠ tool：
 * ① 工作流技能（skill）：SKILL.md 多步工作流，load_skill 按需加载全文（GET /skills 实时读 .pi/skills）
 * ② 数据工具（tool）：单发能力，agent 对话中自然调用，无需用户关心
 * （护栏机制为 harness 内部红线，不对用户展示——2026-10-12 用户拍板移除）
 */
import { useState, useEffect } from 'react';
import { Icon } from './Icons';

interface WorkflowSkill {
  id: string;
  name: string;
  summary?: string;
  description: string;
  version?: string;
  files?: string[];
}

interface ToolItem { id: string; name: string; desc: string }

/** 数据工具面（与 extension 注册面同步：3 query + 6 sentiment + 10 dashboards + 4 social + 交付/协作/web） */
const TOOL_GROUPS: Array<{ label: string; tools: ToolItem[] }> = [
  {
    label: '棱镜三维度',
    tools: [
      { id: 'query_config', name: '配置查询', desc: '产品力主轴：座椅/隔音/轮毂/CLTC/智驾/车机芯片' },
      { id: 'query_reviews', name: '口碑查询', desc: 'owner_reviews + review_tags 维度聚合 pro/con（33 车系池）' },
      { id: 'query_sales', name: '销量查询', desc: '月末零售行 + 终端价同版型对比（CAM 批次）' },
    ],
  },
  {
    label: '舆情',
    tools: [
      { id: 'sentiment_*', name: '舆情六查', desc: '总览/趋势/维度/热帖/竞品对比/事件预警（舆情库）' },
    ],
  },
  {
    label: '社媒（TikHub）',
    tools: [
      { id: 'social_search', name: '社媒搜索', desc: '抖音/小红书/微博/快手/B站 全平台搜帖（免登录）' },
      { id: 'social_post_comments', name: '评论拉取', desc: '评论区购车细节（落地价/配置/现车）' },
      { id: 'social_user_profile', name: '用户画像', desc: '主页资料/粉丝/IP属地（抖音+小红书）' },
      { id: 'social_user_posts', name: '作品列表', desc: '发帖轨迹与决策链时间线（抖音+小红书）' },
    ],
  },
  {
    label: '看板数据',
    tools: [
      { id: 'dashboards ×10', name: '看板工具组', desc: '车系检索/配置对比/全文口碑/销量明细/评分' },
    ],
  },
  {
    label: '交付与协作',
    tools: [
      { id: 'export_document', name: 'xlsx 导出', desc: '表格数据导出原生 Excel + 下载链接' },
      { id: 'web_search 等 ×4', name: '联网查询', desc: '竞品动态/行业新闻/政策法规（库优先原则）' },
      { id: 'ask_user_question', name: '结构化提问', desc: '歧义时向你确认（如车系多候选）' },
    ],
  },
];

export default function SkillsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [workflow, setWorkflow] = useState<WorkflowSkill[] | null>(null);

  useEffect(() => {
    if (!open || workflow) return;
    fetch('/skills').then(r => r.json()).then(j => {
      if (Array.isArray(j?.skills)) setWorkflow(j.skills);
    }).catch(() => {});
  }, [open, workflow]);

  // 工具条目总数（TOOL_GROUPS 里有 ×10 / ×4 聚合项，这里按"条目"计数，不虚报实际工具数）
  const toolCount = TOOL_GROUPS.reduce((s, g) => s + g.tools.length, 0);

  return (
    <>
      <div className={`drawer-scrim ${open ? 'is-open' : ''}`} onClick={onClose} />
      <aside className={`drawer ${open ? 'is-open' : ''}`} aria-hidden={!open} style={{ width: 460 }}>
        <div className="drawer-head">
          <div style={{ flex: 1 }}>
            <div className="eyebrow">Capability Overview</div>
            <div className="drawer-title">能力总览</div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭"><Icon name="x" /></button>
        </div>
        <div className="drawer-body">
          {/* 顶部总量：先给用户一个"这里有什么、有多少"的全局感知 */}
          <div className="cap-summary">
            <div className="cap-sum"><b>{workflow ? workflow.length : '–'}</b><span>工作流技能</span></div>
            <div className="cap-sum"><b>{TOOL_GROUPS.length}</b><span>工具分组</span></div>
            <div className="cap-sum"><b>{toolCount}</b><span>工具条目</span></div>
          </div>

          {/* ① 工作流技能：分区容器 + 行式列表（skill 用赭红左竖条区分于 tool） */}
          <section className="cap-group">
            <header className="cap-head">
              <span className="cap-head-ico"><Icon name="flask" size={13} /></span>
              <div className="cap-head-txt">
                <h3>工作流技能</h3>
                <p>多步工作流 · 对话中按需加载，无需手动触发</p>
              </div>
              <span className="cap-tag">{workflow ? workflow.length : '–'}</span>
            </header>
            <div className="cap-list">
              {workflow === null && <div className="cap-row cap-row-empty">加载中…</div>}
              {workflow && workflow.length === 0 && <div className="cap-row cap-row-empty">暂无已装载的 Skills</div>}
              {(workflow ?? []).map(w => (
                <div key={w.id} className="cap-row is-skill">
                  <div className="cap-row-top">
                    <span className="cap-row-name">{w.name}</span>
                    <code className="cap-row-id">{w.id}{w.version ? ` · v${w.version.replace(/["']/g, '')}` : ''}</code>
                  </div>
                  <p className="cap-row-desc">{w.summary || w.description}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ② 数据工具：外层一个分区容器，内层按业务域分子组 */}
          <section className="cap-group">
            <header className="cap-head">
              <span className="cap-head-ico"><Icon name="layers" size={13} /></span>
              <div className="cap-head-txt">
                <h3>数据工具</h3>
                <p>单发能力 · agent 对话中自动调用</p>
              </div>
              <span className="cap-tag">{toolCount}</span>
            </header>
            <div className="cap-list">
              {TOOL_GROUPS.map(g => (
                <div key={g.label} className="cap-sub">
                  <div className="cap-sub-head">
                    <span className="cap-sub-name">{g.label}</span>
                    <span className="cap-sub-count">{g.tools.length}</span>
                  </div>
                  {g.tools.map(t => (
                    <div key={t.id} className="cap-row">
                      <div className="cap-row-top">
                        <span className="cap-row-name">{t.name}</span>
                        <code className="cap-row-id">{t.id}</code>
                      </div>
                      <p className="cap-row-desc">{t.desc}</p>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </section>
        </div>
        <div className="drawer-foot">
          <button className="btn btn-ghost" onClick={onClose}>关闭</button>
        </div>
      </aside>
    </>
  );
}
