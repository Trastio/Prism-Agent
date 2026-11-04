/**
 * 证据抽屉（右抽屉）：点击数字 → 显示 supported_by + as_of + 口径 + 可复算 SQL
 * 方案 §5.2 / §4 区⑦
 */

import { Icon } from './Icons';

export interface EvidenceNumber {
  value: string | number;
  source: string;
  derived_from?: string[];
}

export interface EvidenceData {
  num: string;
  unit?: string;
  name: string;
  src: string;
  asof: string;
  scope: string;
  /** B2 扩展（对话侧溯源条，change:会话历史与对话侧完善）：submit_conclusion 的 CLAIM 形态。
   *  看板单值点击走原有字段；结论提交走以下扩展字段渲染全文/全列表/数字表。 */
  conclusion_text?: string;
  supported_by?: string[];
  numbers?: EvidenceNumber[];
  data_gaps?: string[];
}

interface Props {
  open: boolean;
  data: EvidenceData | null;
  onClose: () => void;
}

export default function EvidenceDrawer({ open, data, onClose }: Props) {
  return (
    <>
      <div className={`drawer-scrim ${open ? 'is-open' : ''}`} onClick={onClose} />
      <aside className={`drawer ${open ? 'is-open' : ''}`} aria-hidden={!open}>
        <div className="drawer-head">
          <div style={{ flex: 1 }}>
            <div className="eyebrow">Evidence</div>
            <div className="drawer-title">{data?.name ?? '证据'} · 溯源</div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭"><Icon name="x" /></button>
        </div>
        <div className="drawer-body">
          {data ? (
            /* 审查P2-3：CLAIM 形态判据放宽到 supported_by||numbers——缺 conclusion_text 的 CLAIM
               不该落回看板单值模板（会渲染假"可复算 SQL 片段"，误导数据真实性观感） */
            (data.conclusion_text || data.supported_by?.length || data.numbers?.length) ? (
              /* B2：结论 CLAIM 形态（对话侧溯源条打开）——结论全文 + supported_by 全列表 + numbers 表 */
              <>
                <div>
                  <div className="card-meta" style={{ textAlign: 'left', marginBottom: 4 }}>结论全文</div>
                  <div style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{data.conclusion_text}</div>
                </div>
                <dl className="drawer-kv">
                  <div className="row"><dt>as_of</dt><dd>{data.asof}</dd></div>
                  <div className="row"><dt>口径 / scope</dt><dd>{data.scope}</dd></div>
                </dl>
                <div>
                  <div className="card-meta" style={{ textAlign: 'left', marginBottom: 6 }}>
                    supported_by（{data.supported_by?.length ?? 0} 项 · 可复算行 ID）
                  </div>
                  <div className="list">
                    {(data.supported_by ?? []).map((sid, i) => (
                      <div className="list-row" key={i}>
                        <div className="list-main">
                          <div className="list-sub" style={{ fontFamily: 'var(--font-mono)' }}>{sid}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                {data.numbers && data.numbers.length > 0 && (
                  <div>
                    <div className="card-meta" style={{ textAlign: 'left', marginBottom: 6 }}>numbers（{data.numbers.length} 个）</div>
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr>
                            <th style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'left', fontWeight: 500, color: 'var(--ink-2)', background: 'var(--panel)' }}>value</th>
                            <th style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'left', fontWeight: 500, color: 'var(--ink-2)', background: 'var(--panel)' }}>source</th>
                            <th style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'left', fontWeight: 500, color: 'var(--ink-2)', background: 'var(--panel)' }}>derived_from</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.numbers.map((n, i) => (
                            <tr key={i}>
                              <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}>{String(n.value)}</td>
                              <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{n.source}</td>
                              <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', color: n.derived_from?.length ? 'var(--ink-2)' : 'var(--ink-3)' }}>
                                {n.derived_from?.length ? n.derived_from.join(', ') : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
                {data.data_gaps && data.data_gaps.length > 0 && (
                  <div>
                    <div className="card-meta" style={{ textAlign: 'left', marginBottom: 6 }}>数据缺口（声明）</div>
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: 'var(--ink-2)' }}>
                      {data.data_gaps.map((g, i) => <li key={i} style={{ margin: '2px 0', lineHeight: 1.6 }}>{g}</li>)}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              /* 原有：看板单值点击形态 */
              <>
                <div>
                  <div className="drawer-num">{data.num} {data.unit}</div>
                  <div className="card-meta" style={{ textAlign: 'left' }}>{data.name}</div>
                </div>
                <dl className="drawer-kv">
                  <div className="row"><dt>supported_by</dt><dd>{data.src}</dd></div>
                  <div className="row"><dt>as_of</dt><dd>{data.asof}</dd></div>
                  <div className="row"><dt>口径 / scope</dt><dd>{data.scope}</dd></div>
                </dl>
                <div>
                  <div className="card-meta" style={{ textAlign: 'left', marginBottom: 6 }}>可复算片段</div>
                  <div className="drawer-code">
                    SELECT {data.name}{'\n'}
                    FROM {data.src.split('(')[0]}{'\n'}
                    WHERE as_of = '{data.asof}'{'\n'}
                    LIMIT 1;  -- 行 ID 见 supported_by，非通配符
                  </div>
                </div>
              </>
            )
          ) : (
            <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>点击看板数字查看证据</div>
          )}
        </div>
        <div className="drawer-foot">
          <button className="btn btn-ghost" onClick={onClose}>关闭</button>
        </div>
      </aside>
    </>
  );
}
