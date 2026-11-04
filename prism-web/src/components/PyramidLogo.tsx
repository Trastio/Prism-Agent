/**
 * UI-5 Prism Logo · 卢浮宫金字塔抽象 SVG
 * 应用栏左侧标识，替代纯色方块 prism-dot。
 * 主金字塔 + 倒影 + 地平线，保持单色 accent 描边。
 */

export default function PyramidLogo({ size = 18 }: { size?: number }) {
  return (
    <svg
      className="pyramid-logo"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      style={{ flex: 'none' }}
    >
      {/* 地平线 */}
      <line x1="2" y1="14.5" x2="22" y2="14.5" stroke="currentColor" strokeWidth="0.6" opacity="0.45" />
      {/* 主金字塔（卢浮宫正面单点透视） */}
      <path
        d="M12 3 L21 14.5 L3 14.5 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      {/* 背面棱线（透视） */}
      <path
        d="M12 3 L12 14.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
        opacity="0.7"
      />
      {/* 倒影（地平线下，渐淡） */}
      <path
        d="M3 14.5 L12 22 L21 14.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinejoin="round"
        opacity="0.35"
      />
    </svg>
  );
}
