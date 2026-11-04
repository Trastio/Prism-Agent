/** 看板共享组件（对齐原型 VS 令牌 className）+ 手写 SVG 图表 */

import { Icon } from '../Icons';

export function Header({ title, kicker, desc, eyebrowColor }: { title: string; kicker: string; desc: string; eyebrowColor?: string }) {
  return (
    <div className="board-head">
      <div>
        <div className="eyebrow" style={eyebrowColor ? { color: eyebrowColor } : undefined}>{kicker}</div>
        <h2 className="board-title">{title}</h2>
        <p className="board-desc">{desc}</p>
      </div>
    </div>
  );
}

export function Card({ title, meta, children, foot }: { title: string; meta?: string; children: React.ReactNode; foot?: React.ReactNode }) {
  return (
    <div className="card is-hoverable">
      <div className="card-head">
        <h3 className="card-title">{title}</h3>
        {meta && <span className="card-meta">{meta}</span>}
      </div>
      {children}
      {foot && <div className="card-foot">{foot}</div>}
    </div>
  );
}

/** 演示数据卡：默认折叠，点击展开。与真数据物理分区，防 PM 误读 */
import { useState as _useState } from 'react';
export function GapCard({ title, miss, ask }: { title: string; miss: string; ask: string }) {
  return (
    <div className="gap">
      <div className="gap-head">
        <span className="gap-title"><Icon name="unplug" size={16} />{title}</span>
        <span className="evi-badge weak">证据 弱</span>
      </div>
      <p className="gap-miss">{miss}</p>
      <p className="gap-ask"><b>缺什么能坐实：</b>{ask}</p>
    </div>
  );
}

export function Loading() {
  return (
    <div className="skel-row">
      <div className="skel" style={{ width: '60%' }} />
      <div className="skel" style={{ width: '80%' }} />
      <div className="skel" style={{ width: '40%' }} />
    </div>
  );
}
