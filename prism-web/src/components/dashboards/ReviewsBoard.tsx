/**
 * 口碑看板：iframe 嵌 Prism Dashboards 子服务（迁移自 Atuohome_Agent）
 * 口径与交互（多维筛选 / 车系下钻 / 标签分布 / 标签月度趋势）均在子服务内承载。
 * C2：series 有值时经 ?q= 预筛到该车系（dashboard_routes.py 口碑页筛选进 URL 设计）。
 */
import EmbedBoard from './EmbedBoard';

export default function ReviewsBoard({ onEvidence: _onEvidence, series, reloadKey }: {
  onEvidence?: (data: unknown) => void;
  series?: string;
  reloadKey?: number;
}) {
  const path = series ? `/dash/koubei?q=${encodeURIComponent(series)}` : '/dash/koubei';
  return (
    <EmbedBoard
      path={path}
      title="口碑看板"
      reloadKey={reloadKey}
      miss="看板服务（prism-dashboards :8010）经 prism-api 的 /dash/ 反代不可达，iframe 无内容。"
      ask="启动 prism-dashboards 服务，并确认 prism-api 的 /dash/ 反代返回 200。"
    />
  );
}
