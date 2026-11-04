/**
 * 车型配置看板：iframe 嵌 Prism Dashboards 子服务（迁移自 Atuohome_Agent）
 * 承载「逐列选车系+版型 + 横向配置对比表 + 手填计价」。
 * C2：series_id 有值时直达该系（load=1 允许空 spec_id 自动补首个版型，dashboard_routes.py）。
 */
import EmbedBoard from './EmbedBoard';

export default function ConfigBoard({ onEvidence: _onEvidence, seriesId, reloadKey }: {
  onEvidence?: (data: unknown) => void;
  seriesId?: string | number;
  reloadKey?: number;
}) {
  const path = seriesId != null && seriesId !== ''
    ? `/dash/config?series_id=${encodeURIComponent(String(seriesId))}&load=1`
    : '/dash/config';
  return (
    <EmbedBoard
      path={path}
      title="车型配置"
      reloadKey={reloadKey}
      miss="看板服务（prism-dashboards :8010）经 prism-api 的 /dash/ 反代不可达，iframe 无内容。"
      ask="启动 prism-dashboards 服务，并确认 prism-api 的 /dash/ 反代返回 200。"
    />
  );
}
