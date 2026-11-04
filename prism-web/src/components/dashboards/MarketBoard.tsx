/**
 * 销量（市场）看板：iframe 嵌 Prism Dashboards 子服务（迁移自 Atuohome_Agent）
 * 承载「定位散点 / 量价同屏 / 版型结构 / 竞品对比」等模块。
 * C2 限制：子服务市场页无 query 外链支持（market_routes.py market_page 无参数），
 * 车系选择在看板页内完成——Prism 侧 series 不传入（改子服务模板另立项）。
 */
import EmbedBoard from './EmbedBoard';

export default function MarketBoard({ onEvidence: _onEvidence, reloadKey, seriesKey }: {
  onEvidence?: (data: unknown) => void;
  reloadKey?: number;
  seriesKey?: string;
}) {
  // D4（2026-11-02）：对话侧车系联动——子服务支持 ?q= 预选
  const path = seriesKey ? `/dash/market?q=${encodeURIComponent(seriesKey)}` : '/dash/market';
  return (
    <EmbedBoard
      path={path}
      title="销量看板"
      reloadKey={reloadKey}
      miss="看板服务（prism-dashboards :8010）经 prism-api 的 /dash/ 反代不可达，iframe 无内容。"
      ask="启动 prism-dashboards 服务，并确认 prism-api 的 /dash/ 反代返回 200。"
    />
  );
}
