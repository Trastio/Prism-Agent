#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 docs/autohome-agent-workbench-v3.html 的视觉设计（陶土棕三栏工作台）
合并到 src/web/templates/chat.html，保留 chat.html 的全部真实功能
（SSE 流式 / 会话管理 / 工具调用渲染 / 雷达图·拖拽·词云等富组件）。

合并策略（换皮 + 变量桥接）：
  - CSS 顺序：v3 令牌 → 变量桥接别名 → chat.html 组件 CSS → v3 布局/组件 override
    · v3 令牌先定义 --accent/--bg 等
    · 桥接别名让 chat.html 的 var(--primary) 等自动解析到陶土棕
    · chat.html 组件类（.msg-row/.tool-call ...）保留并陶土棕化
    · v3 布局类（.sidebar/.welcome/.chat-area ...）后置 override，主导三栏布局
  - body：v3 三栏骨架 + id 改造兼容 chat.html JS 约定
  - JS：chat.html 完整保留 + 注入 v3 纯展示函数，ask→sendSuggestion 桥接

可重复运行。输出覆盖 src/web/templates/chat.html，chat.html.bak 与 git 作为回滚兜底。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V3 = ROOT / 'docs' / 'autohome-agent-workbench-v3.html'
# chat 的源用 .bak（合并前的原始版本，稳定），避免从已合并的 chat.html 提取导致 inject 重复声明
CHAT_SRC = ROOT / 'src' / 'web' / 'templates' / 'chat.html.bak'
CHAT_OUT = ROOT / 'src' / 'web' / 'templates' / 'chat.html'

v3_text = V3.read_text(encoding='utf-8')
chat_text = CHAT_SRC.read_text(encoding='utf-8')


def extract_between(s, start, end):
    """提取 start 与 end 之间的内容（不含标记）。"""
    i = s.find(start)
    j = s.find(end, i + len(start))
    return s[i + len(start):j]


def cold_to_terra(text):
    """把硬编码青色/冷色替换为陶土棕暖色（CSS 与 JS cssText 共用此表）。"""
    for old, new in {
        '#0e7490': '#8b5e3c', '#0891b2': '#b07849', '#7c3aed': '#8a6b9e',
        '#22d3ee': 'var(--accent)', '#0a0f1e': 'var(--code-bg)',
        '#1e293b': '#44403c', '#131b2e': '#1a1816', '#94a3b8': '#a8a29e',
    }.items():
        text = text.replace(old, new)
    return text


def sanitize_chat_css(css):
    """剥掉 chat.html 源 CSS 的青色令牌块（:root / [data-theme=dark]），
    交由 v3 令牌 + 变量桥接接管；hex 替换共用 cold_to_terra。
    否则青色令牌块排在桥接之后会按 CSS 级联覆盖陶土棕。"""
    def _drop(css, sel, marker):
        pat = re.compile(r'(' + sel + r'\s*\{)([^{}]*)(\})', re.DOTALL)
        out, last = [], 0
        for m in pat.finditer(css):
            if marker in m.group(0):
                out.append(css[last:m.start()]); last = m.end()
        out.append(css[last:])
        return ''.join(out)
    css = _drop(css, r':root', '#0891b2')
    css = _drop(css, r'\[data-theme="dark"\]', '#0a0f1e')
    css = re.sub(r'\n{3,}', '\n\n', css)
    return cold_to_terra(css)


# ---------- 提取 CSS ----------
v3_css = extract_between(v3_text, '<style>', '</style>')
chat_css = extract_between(chat_text, '<style>', '</style>')
chat_css = sanitize_chat_css(chat_css)

# v3 暗色用 .dark，chat.html 用 [data-theme="dark"]，统一到 data-theme 机制
v3_css = v3_css.replace('.dark{', '[data-theme="dark"]{', 1)

# 拆分 v3 CSS 为「令牌」(reset + :root + [data-theme=dark]) 与「组件/布局」(其余)
# 按暗色块结束位置切分，保留开头的 *,*::before reset 规则在 tokens 里
m = re.search(r'\[data-theme="dark"\]\{[^}]*\}', v3_css)
if not m:
    sys.exit('cannot split v3 tokens/components: [data-theme=dark] block not found')
v3_tokens = v3_css[:m.end()]
v3_components = v3_css[m.end():]

# ---------- 提取 chat.html JS（最后一个非 src 的 <script> 内容）----------
script_blocks = re.findall(r'<script>(.*?)</script>', chat_text, re.DOTALL)
chat_js = script_blocks[-1].strip()


def patch_chat_js(js):
    """接入 detail panel 工具调用链追踪 + 富渲染陶土棕化。每个锚点精确匹配一次。"""
    patches = [
        # 1) 每轮对话开始 → 重置工具链
        ("  _lastSentMessage = text;\n\n  setStreaming(true);",
         "  _lastSentMessage = text;\n  try{toolTrace.reset()}catch(e){}\n\n  setStreaming(true);"),
        # 2) 工具调用开始 → 推入工具链
        ("            toolDivMap[toolId] = tcDiv;",
         "            toolDivMap[toolId] = tcDiv;\n            try{toolTrace.add(data.name,data.args,toolId,tcDiv)}catch(e){}"),
        # 3) 工具调用完成 → 更新状态 + 存后端返回的 result 预览
        ("            if (data.ok && data.interactive) {",
         "            try{toolTrace.onResult(data.tool_id,data.ok!==undefined?data.ok:null,data.result,data.error)}catch(e){}\n            if (data.ok && data.interactive) {"),
        # 4) 流结束 → 标记完成
        ("  setStreaming(false);\n  currentController = null;\n  updateSidebar();\n}",
         "  setStreaming(false);\n  try{toolTrace.finish()}catch(e){}\n  currentController = null;\n  updateSidebar();\n}"),
        # 5) 富渲染配色陶土棕化（雷达图/条形图等 canvas 色板）
        ("const VIZ_COLORS = ['#0891b2','#f59e0b','#10b981','#ef4444','#7c3aed','#ec4899','#06b6d4'];",
         "const VIZ_COLORS = ['#b07849','#8a6b9e','#5a8470','#d97706','#c5413b','#3b7ea1','#a06a3d'];"),
    ]
    for old, new in patches:
        if old not in js:
            print(f'  WARN patch anchor not found: {old[:50]!r}')
        else:
            js = js.replace(old, new, 1)
    return js


chat_js = patch_chat_js(chat_js)
chat_js = cold_to_terra(chat_js)

# ---------- 变量桥接别名 ----------
# chat.html 变量名 → v3 陶土棕令牌；让 chat.html 所有 var(--xxx) 自动生效
BRIDGE = r'''
/* ===== 变量桥接：chat.html 变量名 → v3 令牌 ===== */
:root{
  --primary:var(--accent);--primary-hover:var(--accent-hover);
  --primary-light:var(--accent);--primary-bg:var(--accent-soft);
  --primary-glow:rgba(176,120,73,.18);
  --text-secondary:var(--text-2);--text-muted:var(--text-3);
  --surface-hover:var(--surface-2);--surface-glass:var(--surface);
  --border-light:var(--border);
  --radius:var(--radius-md);--radius-xs:6px;
  --success-bg:rgba(77,124,94,.1);--warning-bg:rgba(217,119,6,.1);
  --error-bg:rgba(197,65,59,.1);--info:#3b7ea1;
  --transition:.2s ease;--shadow-glow:0 8px 32px rgba(176,120,73,.12);
  --warning:var(--warn);--shadow:var(--shadow-md);
}
[data-theme="dark"]{
  --primary-glow:rgba(212,165,116,.18);
  --success-bg:rgba(107,184,125,.12);--warning-bg:rgba(251,191,36,.12);
  --error-bg:rgba(248,113,113,.12);--info:#60a5fa;
}
'''

# ---------- body（v3 三栏 + chat.html 功能 id）----------
BODY = '''<div class="sidebar-overlay" id="mobileOverlay" onclick="toggleSidebar(false)"></div>
<div class="toast" id="toast"></div>

<!-- ===== SVG icon defs ===== -->
<svg width="0" height="0" style="position:absolute"><defs>
<symbol id="i-car" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 17H3v-5l2-5h14l2 5v5h-2"/><circle cx="7.5" cy="17" r="1.8"/><circle cx="16.5" cy="17" r="1.8"/><path d="M3 12h18"/></symbol>
<symbol id="i-sliders" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="2" y1="14" x2="6" y2="14"/><line x1="10" y1="8" x2="14" y2="8"/><line x1="18" y1="16" x2="22" y2="16"/></symbol>
<symbol id="i-msg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 8.5-8.5 8.4 8.4 0 0 1 8.5 8.5z"/></symbol>
<symbol id="i-news" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h13v16H6a2 2 0 0 1-2-2V4z"/><path d="M17 7h3v11a2 2 0 0 1-2 2"/><line x1="7" y1="8" x2="14" y2="8"/><line x1="7" y1="12" x2="14" y2="12"/><line x1="7" y1="16" x2="11" y2="16"/></symbol>
<symbol id="i-tag" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12l-7.5 7.5a2 2 0 0 1-2.8 0L3 12.8V4h8.8L20 12z"/><circle cx="7.5" cy="7.5" r="1.2"/></symbol>
<symbol id="i-chart" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="20" x2="20" y2="20"/><rect x="6" y="11" width="3" height="6"/><rect x="11" y="7" width="3" height="10"/><rect x="16" y="13" width="3" height="4"/></symbol>
<symbol id="i-star" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 3 14.7 8.6 21 9.3 16.3 13.7 17.6 20 12 16.8 6.4 20 7.7 13.7 3 9.3 9.3 8.6 12 3"/></symbol>
<symbol id="i-zap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 4 14 11 14 10 22 20 9 13 9 13 2"/></symbol>
<symbol id="i-book" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></symbol>
<symbol id="i-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></symbol>
<symbol id="i-scale" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="M7 21h10"/><path d="M5 7h14"/><path d="M5 7l-2.5 6a3 3 0 0 0 5 0L5 7z"/><path d="M19 7l-2.5 6a3 3 0 0 0 5 0L19 7z"/></symbol>
<symbol id="i-target" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></symbol>
<symbol id="i-trend" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></symbol>
<symbol id="i-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></symbol>
<symbol id="i-paperclip" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7L14 4.5a3.5 3.5 0 0 1 5 5L10.5 18a2 2 0 0 1-3-3L15 7.5"/></symbol>
<symbol id="i-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l8 3v6c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V5l8-3z"/><polyline points="9 12 11 14 15 10"/></symbol>
<symbol id="i-thumbsup" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3z"/><path d="M7 11l4-7a2 2 0 0 1 2 2v4h5a2 2 0 0 1 2 2.3l-1 6A2 2 0 0 1 17 20H7"/></symbol>
<symbol id="i-arrow-r" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></symbol>
<symbol id="i-activity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></symbol>
</defs></svg>

<!-- ==================== Sidebar ==================== -->
<aside class="sidebar" id="sidebar">
  <div class="sb-header">
    <div class="sb-logo"><svg width="18" height="18"><use href="#i-car"/></svg></div>
    <div>
      <div class="sb-title">AutoHome Agent</div>
      <div class="sb-sub">汽车之家智能助手</div>
    </div>
  </div>
  <div class="sb-new"><button class="sb-new-btn" onclick="newChat()">＋ 新对话</button></div>

  <div class="sb-section">
    <div class="sb-label">数据工具 <span class="ct">17</span></div>
    <div class="tg-toggle open" onclick="toggleToolGroup(this)"><span class="tg-ic"><svg width="16" height="16"><use href="#i-car"/></svg></span><span class="tname">车型库</span><span class="tcount">5</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body open">
      <div class="tg-tool" onclick="ask('比亚迪海豚有哪些版本？')"><span class="tn">search_cars</span><span class="td">车型搜索</span></div>
      <div class="tg-tool" onclick="ask('海豚的车型详情？')"><span class="tn">get_model_detail</span><span class="td">车型详情</span></div>
      <div class="tg-tool" onclick="ask('海豚各版本指导价？')"><span class="tn">get_trims</span><span class="td">版本列表</span></div>
      <div class="tg-tool" onclick="ask('海豚的年款换代历史？')"><span class="tn">get_model_generations</span><span class="td">年款换代</span></div>
      <div class="tg-tool" onclick="ask('海豚的同级竞品？')"><span class="tn">get_similar_models</span><span class="td">同级竞品</span></div>
    </div>
    <div class="tg-toggle" onclick="toggleToolGroup(this)"><span class="tg-ic"><svg width="16" height="16"><use href="#i-sliders"/></svg></span><span class="tname">配置</span><span class="tcount">1</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body"><div class="tg-tool" onclick="ask('海豚自由版完整配置？')"><span class="tn">get_config</span><span class="td">完整配置</span></div></div>
    <div class="tg-toggle open" onclick="toggleToolGroup(this)"><span class="tg-ic"><svg width="16" height="16"><use href="#i-msg"/></svg></span><span class="tname">车主口碑</span><span class="tcount">5</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body open">
      <div class="tg-tool" onclick="ask('采集海豚的车主口碑')"><span class="tn">fetch_reviews</span><span class="td">口碑采集</span></div>
      <div class="tg-tool" onclick="ask('海豚口碑分析，看槽点')"><span class="tn">get_review_analysis</span><span class="td">口碑分析</span></div>
      <div class="tg-tool" onclick="ask('海豚口碑搜索异响问题')"><span class="tn">search_reviews</span><span class="td">口碑搜索</span></div>
      <div class="tg-tool" onclick="ask('海豚空间和续航的口碑？')"><span class="tn">get_dimension_reviews</span><span class="td">维度评价</span></div>
      <div class="tg-tool" onclick="ask('海豚的能耗表现？')"><span class="tn">get_energy_analysis</span><span class="td">能耗分析</span></div>
    </div>
    <div class="tg-toggle" onclick="toggleToolGroup(this)"><span class="tg-ic"><svg width="16" height="16"><use href="#i-news"/></svg></span><span class="tname">资讯价格</span><span class="tcount">2</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body">
      <div class="tg-tool" onclick="ask('最近海豚有什么资讯？')"><span class="tn">search_news</span><span class="td">资讯文章</span></div>
      <div class="tg-tool" onclick="ask('海豚经销商报价？')"><span class="tn">get_dealer_price</span><span class="td">经销商报价</span></div>
    </div>
    <div class="tg-toggle" onclick="toggleToolGroup(this)"><span class="tg-ic"><svg width="16" height="16"><use href="#i-chart"/></svg></span><span class="tname">销量</span><span class="tcount">1</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body"><div class="tg-tool" onclick="ask('海豚近半年销量？')"><span class="tn">get_sales_data</span><span class="td">月度销量</span></div></div>
    <div class="tg-toggle" onclick="toggleToolGroup(this)"><span class="tg-ic"><svg width="16" height="16"><use href="#i-star"/></svg></span><span class="tname">评分</span><span class="tcount">1</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body"><div class="tg-tool" onclick="ask('海豚和ID.3加权评分对比')"><span class="tn">score_models</span><span class="td">加权评分</span></div></div>
    <div class="tg-toggle" onclick="toggleToolGroup(this)"><span class="tg-ic" style="color:var(--c-agent)"><svg width="16" height="16"><use href="#i-zap"/></svg></span><span class="tname">Agent 增强</span><span class="tcount">2</span><svg class="chev"><use href="#i-chev"/></svg></div>
    <div class="tg-body">
      <div class="tg-tool" onclick="toolInfo('load_skill')"><span class="tn">load_skill</span><span class="td">加载方法论</span></div>
      <div class="tg-tool" onclick="toolInfo('spawn_subagent')"><span class="tn">spawn_subagent</span><span class="td">子任务调研</span></div>
    </div>
  </div>

  <div class="sb-divider"></div>

  <div class="sb-section">
    <div class="sb-label">方法论 Skill <span class="ct">3</span></div>
    <div class="skill-card" onclick="skillInfo('config')"><div class="sk-ic"><svg width="15" height="15"><use href="#i-book"/></svg></div><div class="sk-body"><div class="sk-name">config</div><div class="sk-desc">配置对比方法论 · 多车型差异</div></div></div>
    <div class="skill-card" onclick="skillInfo('decision')"><div class="sk-ic"><svg width="15" height="15"><use href="#i-book"/></svg></div><div class="sk-body"><div class="sk-name">decision</div><div class="sk-desc">购车决策框架 · 偏好评分推荐</div></div></div>
    <div class="skill-card" onclick="skillInfo('market')"><div class="sk-ic"><svg width="15" height="15"><use href="#i-book"/></svg></div><div class="sk-body"><div class="sk-name">market</div><div class="sk-desc">市场分析方法 · 销量竞品矩阵</div></div></div>
  </div>

  <div class="sb-divider"></div>

  <div class="sb-section">
    <div class="sb-label">对话历史</div>
    <div class="sidebar-list" id="sidebarList"></div>
  </div>

  <div class="sb-footer">
    <span class="session-badge" id="sessionBadge"></span>
    <button class="sb-theme-btn" onclick="clearChat()" title="清空对话" style="margin-bottom:6px"><svg width="14" height="14"><use href="#i-shield"/></svg><span>清空对话</span></button>
    <button class="sb-theme-btn" onclick="toggleTheme()" id="themeBtn"><svg width="14" height="14"><use href="#i-book"/></svg><span id="themeText">切换暗色</span></button>
  </div>
</aside>

<!-- ==================== Main ==================== -->
<div class="main">
  <header class="header">
    <button class="header-btn menu-btn" onclick="toggleSidebar()" title="切换侧栏"><svg width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
    <div class="header-title"><span class="crumb">autohome agent</span><span id="htitle">汽车之家智能助手</span></div>
    <div class="spacer"></div>
    <span class="header-status"><span class="d"></span>17 工具 · 3 方法论 · 全部在线</span>
    <button class="header-btn" onclick="exportChat()" title="导出对话"><svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></button>
    <button class="header-btn" onclick="toggleDetail()" title="工具与方法论说明"><svg width="19" height="19"><use href="#i-activity"/></svg></button>
  </header>

  <div class="chat-area" id="chatArea">
    <div class="welcome" id="welcomeBlock">
      <div class="welcome-head">
        <div class="welcome-logo"><svg width="26" height="26"><use href="#i-car"/></svg></div>
        <h1>汽车之家智能助手</h1>
        <p>自然语言提问，Agent 自主调用 17 个数据维度，覆盖车型查询、配置对比、口碑分析、竞品研究、市场洞察与购车决策。</p>
        <div class="cap-line"><b>17</b> 数据工具 · <b>3</b> 方法论 · <b>6</b> 类用法 · 全程数据溯源</div>
      </div>
      <div class="usecases" id="usecases"></div>
      <div class="welcome-tips">
        <span><svg width="13" height="13"><use href="#i-msg"/></svg>直接提问即可</span>
        <span><svg width="13" height="13"><use href="#i-sliders"/></svg>左侧查看工具与方法论</span>
        <span><svg width="13" height="13"><use href="#i-activity"/></svg>右侧查看调用流程</span>
        <span><svg width="13" height="13"><use href="#i-paperclip"/></svg>回答标注数据来源</span>
      </div>
    </div>
  </div>

  <div class="input-area">
    <div class="input-wrap">
      <div class="input-box"><textarea id="messageInput" rows="1" placeholder="问点什么… 例如：比亚迪海豚车主最常提到的槽点是什么？" oninput="resizeInput(this)" onkeydown="onKey(event)"></textarea></div>
      <button class="stop-btn" id="stopBtn" onclick="stopGeneration()" title="停止生成"><svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><rect x="6" y="6" width="12" height="12" rx="2"/></svg></button>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()"><svg width="17" height="17"><use href="#i-arrow-r"/></svg></button>
    </div>
    <div class="input-hint">Enter 发送 · Shift+Enter 换行 · Agent 会自主选择工具组合并标注数据来源</div>
  </div>
</div>

<!-- ==================== Detail panel ==================== -->
<div class="detail-panel" id="detailPanel">
  <div class="dp-header">
    <span class="dp-title"><svg><use href="#i-activity"/></svg>工具与方法论</span>
    <span class="dp-count" id="dpCount">说明</span>
    <button class="dp-close" onclick="closeDetail()">✕</button>
  </div>
  <div class="dp-body">
    <div class="dp-status" id="dpStatus" style="display:none"></div>
    <div class="dp-tool-list" id="dpToolList"></div>
    <div class="dp-divider" id="dpDivider" style="display:none"></div>
    <div class="dp-content-label" id="dpContentLabel" style="display:none">返回数据预览</div>
    <div class="dp-content" id="dpContent" style="display:none"></div>
    <div class="dp-nav" id="dpNav" style="display:none"><button class="dp-nav-btn" onclick="navTool(-1)">← 上一个</button><button class="dp-nav-btn" onclick="navTool(1)">下一个 →</button></div>
  </div>
</div>
'''

# ---------- 注入的 v3 展示函数（去冲突：不含 sendMessage/toggleSidebar/toggleTheme/newChat 等已在 chat.html 定义的同名函数）----------
INJECT_JS = r'''
/* ===== v3 展示函数注入（工具树/方法论/详情面板，纯前端展示）===== */
function svgIcon(id,size=20){return `<svg width="${size}" height="${size}"><use href="#${id}"/></svg>`}

const USECASES=[
  {icon:'i-search',name:'车型情报',en:'vehicle intel',desc:'查任何车型的参数、版本、年款换代、同级竞品',sample:'比亚迪海豚有哪些版本？各版本指导价多少？'},
  {icon:'i-scale',name:'配置对标',en:'config benchmark',desc:'单车型完整配置，或多车型逐项差异对比',sample:'海豚自由版和骑士版配置差在哪？'},
  {icon:'i-msg',name:'口碑洞察',en:'voice of owner',desc:'采集真实车主口碑，AI 提取买点槽点、维度、能耗',sample:'海豚车主最常提到的槽点是什么？'},
  {icon:'i-news',name:'资讯价格',en:'news & price',desc:'车型相关资讯评测文章、经销商终端报价',sample:'最近海豚有什么新车资讯？终端报价多少？'},
  {icon:'i-target',name:'购车决策',en:'purchase decision',desc:'收集偏好 → 多维度加权评分 → 推荐排序+解释',sample:'12万家用纯电代步车，推荐一下并说明理由'},
  {icon:'i-trend',name:'市场研究',en:'market research',desc:'销量趋势、竞品矩阵、深度市场调研',sample:'10-15万纯电SUV市场，主流车型销量怎么排？'},
];
function renderUsecases(){
  const el=document.getElementById('usecases');if(!el)return;
  el.innerHTML=USECASES.map(u=>`
    <div class="uc" onclick="ask('${u.sample.replace(/'/g,"\\'")}')">
      <div class="uc-head"><div class="uc-ic">${svgIcon(u.icon,20)}</div><div><div class="uc-title">${u.name}</div><div class="uc-en">${u.en}</div></div></div>
      <div class="uc-desc">${u.desc}</div>
      <div class="uc-sample"><span class="arrow">${svgIcon('i-arrow-r',12)}</span>${u.sample}</div>
    </div>`).join('');
}
const TOOL_INFO={
  load_skill:{n:'load_skill',desc:'按需加载方法论 Skill。LLM 在遇到配置对比、购车决策、市场研究等专业场景时，主动调用此工具加载对应方法论，按框架指引后续工具调用。',extras:[['类型','本地工具（主进程）'],['触发','配置对比 / 购车决策 / 市场研究'],['实现','src/agent/skills.py']]},
  spawn_subagent:{n:'spawn_subagent',desc:'在独立上下文中执行深度调研。适合「分析10-15万纯电SUV市场」这类需要大量工具调用、会污染主对话上下文的复杂任务。',extras:[['类型','本地工具（主进程）'],['触发','复杂多步骤调研'],['实现','src/agent/subagent.py']]}
};
const SKILL_INFO={
  config:{n:'config',desc:'配置对比方法论。对比多车型配置时，按"维度归类 → 差异识别 → 加分配置 → 优劣结论"框架输出对比表。',extras:[['路径','skills/config/SKILL.md'],['触发','配置对标用法'],['加载','load_skill(config)']]},
  decision:{n:'decision',desc:'购车决策框架。收集用户偏好（价位/用途/优先级）→ 多维度加权评分 → 推荐排序 + 解释理由。',extras:[['路径','skills/decision/SKILL.md'],['触发','购车决策用法'],['加载','load_skill(decision)']]},
  market:{n:'market',desc:'市场分析方法。结合销量数据、竞品识别、口碑分析，输出市场格局判断和趋势分析。',extras:[['路径','skills/market/SKILL.md'],['触发','市场研究用法'],['加载','load_skill(market)']]}
};
function toolInfo(n){const t=TOOL_INFO[n];if(t)openInfoPanel(t,'i-zap')}
function skillInfo(n){const s=SKILL_INFO[n];if(s)openInfoPanel(s,'i-book')}
function openInfoPanel(info,icon){
  const dp=document.getElementById('detailPanel');if(!dp)return;
  dp.classList.add('open');
  const setNone=id=>{const e=document.getElementById(id);if(e)e.style.display='none'};
  setNone('dpStatus');setNone('dpDivider');setNone('dpContentLabel');setNone('dpContent');setNone('dpNav');
  const c=document.getElementById('dpCount');if(c)c.textContent='说明';
  const list=document.getElementById('dpToolList');
  list.innerHTML=`<div style="display:flex;align-items:center;gap:8px;padding:2px 0 10px">
      <span style="width:26px;height:26px;border-radius:7px;background:var(--c-skill-soft);color:var(--c-skill);display:flex;align-items:center;justify-content:center">${svgIcon(icon,15)}</span>
      <span style="font-size:13px;font-weight:600;font-family:var(--mono);color:var(--text)">${info.n}</span></div>
    <div style="font-size:12.5px;color:var(--text-2);line-height:1.7;padding:0 2px 10px">${info.desc}</div>`;
  info.extras.forEach(([k,v])=>{
    list.innerHTML+=`<div style="display:flex;gap:10px;padding:6px 2px;border-top:1px dashed var(--border);font-size:11.5px"><span style="width:70px;color:var(--text-3);font-family:var(--mono);flex-shrink:0">${k}</span><span style="color:var(--text-2);flex:1">${v}</span></div>`;
  });
}
function toggleToolGroup(btn){btn.classList.toggle('open');btn.nextElementSibling.classList.toggle('open')}
function toggleDetail(){const dp=document.getElementById('detailPanel');if(dp)dp.classList.toggle('open')}
function closeDetail(){const dp=document.getElementById('detailPanel');if(dp)dp.classList.remove('open')}
function navTool(){}
/* 工具树点击 → 桥接到真实发送 */
function ask(t){sendSuggestion(t)}
/* 输入框自适应高度 + Enter 发送 */
function resizeInput(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,120)+'px'}
function onKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}}

/* ===== 工具调用链追踪（detail panel 真实数据，订阅后端 tool_call/tool_result 事件）===== */
const toolTrace=(function(){
  let items=[],byId={},t0=null,done=false;
  const $=id=>document.getElementById(id);
  function reset(){items=[];byId={};t0=Date.now();done=false;render()}
  function add(name,args,toolId){const it={name:name||'',args:args||'',toolId:toolId||'',status:'pending',result:null,error:null,t0:Date.now(),t1:null};items.push(it);if(toolId)byId[toolId]=it;render()}
  function onResult(toolId,ok,result,error){
    let it=(toolId&&byId[toolId])?byId[toolId]:null;
    if(!it){for(let i=items.length-1;i>=0;i--){if(items[i].status==='pending'){it=items[i];break}}}
    if(!it)return;
    if(toolId&&!it.toolId){it.toolId=toolId;byId[toolId]=it}
    it.status=(ok===true)?'ok':((error||ok===false)?'error':'ok');
    it.result=result||null;it.error=error||null;it.t1=Date.now();render();
  }
  function finish(){done=true;render()}
  function fmtArgs(a){try{const o=JSON.parse(a);return Object.entries(o).map(([k,v])=>k+'='+String(v).slice(0,18)).join(', ')}catch(e){return String(a).slice(0,40)}}
  function render(){
    const list=$('dpToolList');if(!list)return;
    const cnt=$('dpCount'),st=$('dpStatus');
    if(cnt)cnt.textContent=items.length?items.length+' 步':'说明';
    if(st){
      const dN=items.filter(i=>i.status!=='pending').length,pN=items.length-dN;
      const dur=items.length?Math.round((((items[items.length-1].t1)||Date.now())-((items[0]&&items[0].t0)||t0||Date.now()))/100)/10:0;
      const lab=done?'已完成':(pN?'执行中…':'等待');
      st.style.display=items.length?'':'none';
      st.innerHTML=`<div class="dp-status-row"><span class="sd${done?'':' busy'}"></span><span class="sl">${lab}</span></div><div class="dp-status-meta">${items.length} 工具调用 · ${dN} 完成 · ${dur}s</div>`;
    }
    list.innerHTML=items.map((it,i)=>{
      const sc=it.status==='ok'?'m-ok':(it.status==='error'?'m-bg':'');
      const ic=svgIcon(it.status==='ok'?'i-check':'i-activity',11);
      const lb=it.status==='ok'?'成功':(it.status==='error'?'出错':'运行');
      const tm=it.t1?((it.t1-it.t0)/1000).toFixed(1)+'s':'';
      const dn=(typeof TOOL_NAMES!=='undefined'&&TOOL_NAMES[it.name])||it.name;
      return `<div class="dp-tool-item" data-idx="${i}" onclick="toolTrace.show(${i})"><span class="dp-tool-idx">${i+1}</span><div class="dp-tool-info"><div class="dp-tool-name">${dn}</div><div class="dp-tool-desc">${escHtml(fmtArgs(it.args))}</div><div class="dp-tool-meta">${sc?`<span class="${sc}">${ic}${lb}</span>`:''}${tm?`<span class="m-time">${tm}</span>`:''}</div></div></div>`;
    }).join('');
    if(items.length===1&&window.innerWidth>1024&&!$('detailPanel').classList.contains('open')){$('detailPanel').classList.add('open')}
  }
  function show(i){
    const it=items[i];if(!it)return;
    document.querySelectorAll('.dp-tool-item').forEach((el,j)=>el.classList.toggle('active',j===i));
    $('dpDivider').style.display='';$('dpContentLabel').style.display='';$('dpContent').style.display='';
    $('dpContentLabel').textContent=it.error?'错误信息':'返回数据预览';
    let body;
    if(it.error){body=escHtml(String(it.error))}
    else if(it.result){try{body=escHtml(JSON.stringify(JSON.parse(it.result),null,2))}catch(e){body=escHtml(it.result)}}
    else{body='<span style="color:var(--text-3)">（暂无返回数据）</span>'}
    $('dpContent').innerHTML=body;
    if(!$('detailPanel').classList.contains('open'))$('detailPanel').classList.add('open');
  }
  return {reset,add,onResult,finish,show,get items(){return items}};
})();

document.addEventListener('DOMContentLoaded',()=>{renderUsecases()});
'''

# ---------- 拼装 ----------
OUTPUT = '''<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AutoHome Agent · 汽车之家智能助手</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
/* ===== v3 设计令牌（陶土棕）===== */
__V3_TOKENS__
__BRIDGE__
/* ===== chat.html 组件样式（消息/工具调用/富渲染，变量已桥接陶土棕）===== */
__CHAT_CSS__
/* ===== v3 布局/组件 override（主导三栏骨架）===== */
__V3_COMPONENTS__
</style>
</head>
<body data-theme="light">
__BODY__
<script>
__CHAT_JS__

__INJECT_JS__
</script>
</body>
</html>
'''

output = (OUTPUT
          .replace('__V3_TOKENS__', v3_tokens.strip())
          .replace('__BRIDGE__', BRIDGE.strip())
          .replace('__CHAT_CSS__', chat_css.strip())
          .replace('__V3_COMPONENTS__', v3_components.strip())
          .replace('__BODY__', BODY.strip())
          .replace('__CHAT_JS__', chat_js)
          .replace('__INJECT_JS__', INJECT_JS.strip()))

CHAT_OUT.write_text(output, encoding='utf-8')
print(f'✓ 已生成 {CHAT_OUT.relative_to(ROOT)}')
print(f'  行数: {output.count(chr(10)) + 1}  大小: {len(output.encode("utf-8"))} bytes')

# ---------- 自检 ----------
print('\n=== 自检 ===')
required_ids = ['chatArea', 'messageInput', 'sendBtn', 'stopBtn', 'sessionBadge',
                'sidebar', 'sidebarList', 'mobileOverlay', 'toast', 'welcomeBlock', 'detailPanel']
missing = [i for i in required_ids if f'id="{i}"' not in output]
print(f'必需 DOM id 缺失: {missing or "无 ✓"}')

# 关键函数应只定义一次（chat.html 真实版）；v3 注入不应重复定义这些
critical_fns = ['function sendMessage', 'function toggleSidebar', 'function newChat',
                'function toggleTheme', 'function clearChat', 'function sendSuggestion',
                'function addToolCall', 'function stopGeneration', 'function exportChat']
for fn in critical_fns:
    cnt = output.count(fn)
    flag = '✓' if cnt == 1 else f'⚠ 定义 {cnt} 次'
    print(f'  {fn}: {flag}')

# 注入的展示函数应存在
inject_fns = ['function svgIcon', 'function renderUsecases', 'function toolInfo',
              'function skillInfo', 'function openInfoPanel', 'function ask']
miss_inject = [f for f in inject_fns if f not in output]
print(f'注入展示函数缺失: {miss_inject or "无 ✓"}')

print(f'\nchat.html.bak 与 git 可作为回滚兜底')
