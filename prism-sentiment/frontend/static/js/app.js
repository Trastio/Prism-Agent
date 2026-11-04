const { createApp } = Vue;

const CHART_COLORS = {
    accent: '#c96442', accentD: '#a44f33',
    pos: '#2348b8', neg: '#9c2a25', neu: '#9e9e9e',
    info: '#3a6ea5', grid: '#f0ece5', muted: '#5a564e',
};
const SENTIMENT_CN2EN = { "正面": "positive", "负面": "negative", "中性": "neutral" };

function hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${Number(alpha).toFixed(2)})`;
}

// mount() 返回根组件代理；挂全局供 dialog.js 等外部脚本取 vm。
// 勿改回 app._instance 内部字段——vue 3.5+ mounted 后该字段为 null（unpkg 浮动 tag 漂移踩过）
window.__vmProxy = createApp({
    data() {
        const today = new Date().toISOString().slice(0, 10);
        const start30 = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
        return {
            vehicles: [],
            currentVehicleId: "",
            loadingVehicle: false,  // P1-6：切车加载遮罩
            overview: {},
            trendData: [],
            sentimentTrendData: [],
            commentSentimentTrendData: [],  // T1.5: 评论级情感趋势（负面声量曲线数据源）
            platformDist: [],
            topPosts: [],
            negativeRadar: {},
            eventTimeline: [],
            dimSentiment: [],
            // 2026-10-20：热帖只看在采三平台（抖音/小红书），车质网按投诉线索展示；
            // 去掉「全部」以免混入已停采平台（快手/微博）的历史存量
            hotPostsTab: "douyin",
            hotPostsTabOptions: [
                { key: 'douyin', label: '抖音' },
                { key: 'xiaohongshu', label: '小红书' },
                { key: 'chezhiwang', label: '车质网' },
            ],
            eventTabOptions: [
                { key: 'all', label: '社媒事件' },
            ],
            wordCloudData: [],
            // 分平台词云（2026-10-20）：抖音 / 小红书 / 车质网 各一份，tab 切换复用同一 canvas
            platformWordClouds: { douyin: [], xiaohongshu: [], chezhiwang: [] },
            wcTab: 'douyin',
            // Posts & reports (overflow panels)
            posts: { items: [], total: 0, page: 1, size: 20 },
            reports: [],
            controversialPosts: [],
            postsFilter: { sentiment: "", platform: "" },
            expandedReport: null,
            // 关注清单（手动标记，无状态机）
            showWatchlist: false,
            watchItems: [],
            // 车队总览（D14：一行一车列表）
            showFleet: false,
            fleetOverview: [],
            fleetLoading: false,
            // 缺陷话题簇（3.x 话题发酵）
            defectThemes: [],
            defectLoading: false,
            // 7天增量视图（D13）：窗 ≤7 天时切换为增量模式
            incrementOverview: {},
            incrementLoading: false,
            // UI state
            rangeStart: start30,
            rangeEnd: today,
            loading: false,
            toasts: [],
            showAllPosts: false,
            showReportPanel: false,
            showOverflow: false,
            showAddModal: false,
            // Pipeline
            pipelinePhase: "idle",
            pipelineInfo: {},
            pipelinePollTimer: null,
            // P2-1：刷新/全车采集状态（无下划线，只放 data，Vue3 不代理 _ 前缀）
            refreshing: false,
            fleetCollecting: false,
            fleetPollTimer: null,
            fleetStartedVids: [],
            fleetStartTime: 0,
            collectionProgress: {},
            lastCollectionTime: "",
            // Search
            searchQuery: "",
            searchResults: [],
            searchDebounceTimer: null,
            // Modals
            newVehicle: { name: "", brand: "", search_keywords: "" },
            suggestResults: [],
            suggestHighlight: -1,  // U-7：搜索框键盘导航高亮索引
            imeComposing: false,  // N-5：IME 组合态标记
            postDetailOpen: false,
            postDetail: {},
            // Report
            reportLoading: false,
            reportLoadingType: null,
            reportContent: "",
            // Time presets
            timePresets: [
                { label: "7天", days: 7 },
                { label: "30天", days: 30 },
                { label: "全部", days: 0 },
            ],
            // Event tab filter
            eventTab: "all",
            // ECharts instances（change2 块A：discussion/opinionTags/negativeTrend 三实例随卡片退役）
            // 2026-10-20：图表实例必须 Vue.markRaw 包裹（见各 render 函数）。放进 data 会被深响应式代理，
            // resize() 时 seriesModel.coordinateSystem 丢失，抛 "Cannot read properties of undefined (reading 'type')"
            attentionChart: null,
            sentimentChart: null,
            platformChart: null,
            dimPosChart: null,     // UI 优化：维度口碑拆为上下两图（上=正面得分）
            dimNegChart: null,     //                      下=评论负面占比
            sentimentDonutChart: null,
            commentSentimentDonutChart: null,
            commentSentimentOverview: {},
            wordCloudChart: null,
        };
    },
    computed: {
        // --- 负面雷达 ---
        negRatePct() {
            const r = this.negativeRadar?.negative_rate;
            return (r === undefined || r === null) ? '--' : (r * 100).toFixed(1);
        },
        riskLevelLabel() {
            return { low: '低', medium: '中', high: '高', insufficient: '样本不足' }[this.negativeRadar?.risk_level] || '--';
        },
        riskReasonsText() {
            return (this.negativeRadar?.risk_reasons || []).join(' · ') || '—';
        },
        negWowArrow() {
            const w = this.negativeRadar?.negative_wow;
            return (w === null || w === undefined) ? '' : (w >= 0 ? '▲' : '▼');
        },
        negWowClass() {
            const w = this.negativeRadar?.negative_wow;
            return (w === null || w === undefined) ? '' : (w >= 0 ? 'neg-wow-up' : 'neg-wow-down');
        },
        currentVehicleName() {
            const v = this.vehicles.find(v => v.id === this.currentVehicleId);
            return v ? v.name : '';
        },
        // 7天增量模式：用户窗 ≤7 天时切增量视图（D13），不再缩窗复看常规组件
        isIncrementMode() {
            if (!this.rangeStart || !this.rangeEnd) return false;
            const days = (new Date(this.rangeEnd) - new Date(this.rangeStart)) / 86400000;
            return days >= 0 && days <= 7;
        },
        currentVehicleBrand() {
            const v = this.vehicles.find(v => v.id === this.currentVehicleId);
            return v ? v.brand : '';
        },
        eventCount() {
            // 3.1 发酵话题追踪（2026-10-20）：新闻事件彻底剔除，只计社媒话题
            return (this.eventTimeline || []).filter(e => e.source !== 'news').length;
        },
        socialEventCount() {
            return (this.eventTimeline || []).filter(e => e.source === 'social').length;
        },
        newsEventCount() {
            return (this.eventTimeline || []).filter(e => e.source === 'news').length;
        },
        // 3.1 发酵话题追踪（2026-10-20）：仅社媒聚类，按当前热度（窗内帖量）降序
        filteredEventTimeline() {
            const list = (this.eventTimeline || []).filter(e => e.source !== 'news');
            return list.slice().sort((a, b) => (b.post_count || 0) - (a.post_count || 0));
        },
        filteredHotPosts() {
            // 车质网 tab：按互动量排序的投诉线索（后端无"投诉量/增速"字段，口径见卡片注记）
            if (this.hotPostsTab === 'all') return this.topPosts.slice(0, 5);
            return this.topPosts.filter(p => p.platform === this.hotPostsTab).slice(0, 5);
        },
        /* 平台情感分布（2026-10-20 新增）：只看抖音 / 小红书 / 车质网三平台
           分母用"已分析帖"（正+中+负），未分析帖单列，不稀释占比 */
        platformSentimentRows() {
            const ORDER = ['douyin', 'xiaohongshu', 'chezhiwang'];
            return ORDER.map(key => {
                const r = (this.platformDist || []).find(p => p.platform === key);
                if (!r || !r.count) return null;
                const pos = r.positive || 0, neu = r.neutral || 0, neg = r.negative || 0;
                const analyzed = pos + neu + neg;
                const base = analyzed || r.count || 1;
                // 2026-10-20：保留 1 位小数并让中性取余数，避免各自四舍五入后合计 ≠100%（条宽溢出/留缝）
                const posPct = +(pos / base * 100).toFixed(1);
                const negPct = +(neg / base * 100).toFixed(1);
                const neuPct = +Math.max(0, 100 - posPct - negPct).toFixed(1);
                return {
                    platform: key, name: this.platformLabel(key), count: r.count,
                    positive: pos, neutral: neu, negative: neg, unknown: r.unknown || 0, analyzed,
                    posPct,
                    neuPct,
                    negPct,
                };
            }).filter(Boolean);
        },
        /* 搜索峰值归因：取合成指数最高日，回查该周 event_annotations（后端按周聚类） */
        searchPeakNote() {
            const raw = (this.trendData && this.trendData.data) || [];
            const ann = (this.trendData && this.trendData.event_annotations) || {};
            if (!raw.length) return '';
            let peak = null;
            raw.forEach(d => {
                const v = typeof d.search_index === 'number' ? d.search_index
                    : (typeof d.attention_index === 'number' ? d.attention_index : null);
                if (v !== null && (!peak || v > peak.v)) peak = { date: d.date, v };
            });
            if (!peak) return '';
            const dt = new Date(peak.date + 'T00:00:00');
            const dow = dt.getDay();                                 // 与后端 event_annotations 一致：周日起
            const ws = new Date(dt.getTime() - dow * 864e5);
            const p2 = n => String(n).padStart(2, '0');
            const key = `${ws.getFullYear()}-${p2(ws.getMonth() + 1)}-${p2(ws.getDate())}`;
            const tags = ann[key] || [];
            const md = peak.date.slice(5);
            if (!tags.length) {
                // 2026-10-20：事件标注按「起始周」分桶，跨周持续的话题会被漏掉。
                // 回退到「峰值日仍在持续的话题」，只做同期相关性提示，不写成因果。
                const overlapping = (this.eventTimeline || [])
                    .filter(e => e.source !== 'news' && e.start_date && e.end_date && e.start_date <= peak.date && e.end_date >= peak.date)
                    .sort((a, b) => (b.post_count || 0) - (a.post_count || 0));
                if (overlapping.length) {
                    const top = overlapping[0];
                    return `搜索峰值出现在 ${md}，同期热度最高的话题是「${top.event_tag}」（${top.post_count} 帖）；搜索指数与话题热度为同期相关，非因果`;
                }
                return `搜索峰值出现在 ${md}，该周无事件聚类标注可归因`;
            }
            return `搜索峰值出现在 ${md}，主要由「${tags.slice(0, 3).join('」「')}」带动`;
        },
        sentimentTotal() {
            return (this.overview.positive || 0) + (this.overview.negative || 0) + (this.overview.neutral || 0);
        },
        positivePct() {
            if (this.overview.positive_pct !== undefined && this.overview.positive_pct !== null) {
                return Number(this.overview.positive_pct).toFixed(1);
            }
            if (!this.sentimentTotal) return '--';
            return ((this.overview.positive / this.sentimentTotal) * 100).toFixed(1);
        },
        negativePct() {
            if (this.overview.negative_pct !== undefined && this.overview.negative_pct !== null) {
                return Number(this.overview.negative_pct).toFixed(1);
            }
            if (!this.sentimentTotal) return '--';
            return ((this.overview.negative / this.sentimentTotal) * 100).toFixed(1);
        },
        neutralPct() {
            if (this.overview.neutral_pct !== undefined && this.overview.neutral_pct !== null) {
                return Number(this.overview.neutral_pct).toFixed(1);
            }
            if (!this.sentimentTotal) return '--';
            return ((this.overview.neutral / this.sentimentTotal) * 100).toFixed(1);
        },
        healthColor() {
            const s = this.overview.health_score;
            if (s == null) return "var(--muted)";  // P2-6：无数据不走红字
            if (s >= 70) return "var(--positive)";
            // UI 一致性：健康分公式中枢为 50（50 + (正-负)/总量×50），中档阈值统一为 50（与车队总览一致，原为 40）
            if (s >= 50) return "var(--neutral)";
            return "var(--negative)";
        },
        searchHeat() {
            const data = this.trendData?.data || [];
            if (!data.length) return '--';
            // 优先多平台合成指数（0-100，抖音+小红书各按窗口内 max 归一后平均）；
            // 无指数数据回退 attention_index（互动合成口径）
            const last = data[data.length - 1];
            if (last.search_index !== undefined && last.search_index !== null) {
                return Math.round(last.search_index).toString();
            }
            const ai = last.attention_index;
            if (ai === undefined || ai === null) return '--';
            if (ai >= 10000) return (ai / 10000).toFixed(1) + '万';
            if (ai >= 1000) return (ai / 1000).toFixed(1) + 'k';
            return Math.round(ai).toString();
        },
        heatPercentile() {
            const data = this.trendData?.data || [];
            if (!data.length) return '';
            const heat = d => (d.search_index ?? d.attention_index) || 0;
            const last = data[data.length - 1];
            const ai = heat(last);
            if (!ai) return '';  // UI 修正：无热度数据时不显示百分位，避免误显“前 100%”
            const vals = data.map(heat).sort((a, b) => a - b);
            let rank = 0;  // UI 修正：初值 1→0，最低热度应为“前 100%”（原会误显“前 0%”）
            for (let i = 0; i < vals.length; i++) {
                if (ai > vals[i]) rank = (i + 1) / vals.length;
            }
            // rank=1.0 表示"比窗口内所有天都高"（前 0%）；rank=0 表示"最低"
            // "前 X%" 语义 = 比 X% 的时间热度更高，比 P54 更直觉
            const pct = Math.round((1 - rank) * 100);
            return `前 ${pct}%`;
        },
        sparseSince() {
            // 数据积累期标注：首个"前向 7 天帖量 ≥ 峰值周 20%"的日子 = 密集采集
            // 起点。此前区间（2 词限量/未接入时代）每周仅 1-3 帖，趋势断崖是
            // 采集密度差异不是舆情变化——顶部黄字提示防误读。
            const pts = this.trendData?.data || [];
            if (pts.length < 14) return '';
            const totals = pts.map(p => (p.discussion_volume || 0) + (p.media_volume || 0));
            let max7 = 0;
            const rolls = [];
            for (let i = 0; i + 7 <= totals.length; i++) {
                const w = totals.slice(i, i + 7).reduce((a, b) => a + b, 0);
                rolls.push([i, w]);
                max7 = Math.max(max7, w);
            }
            if (max7 < 10) return '';
            // U-10：改中位数阈值（原峰值*0.2 换窗时峰值跳变导致提示抖动）
            const sorted = rolls.map(r => r[1]).sort((a, b) => a - b);
            const median = sorted[Math.floor(sorted.length / 2)];
            const threshold = (median > 0 ? median : max7 * 0.2) * 0.3;
            for (const [i, w] of rolls) {
                if (w >= threshold) return pts[i].date === pts[0].date ? '' : pts[i].date;
            }
            return '';
        },
        renderedReport() {
            if (!this.reportContent) return "";
            return this.renderMarkdown(this.reportContent);
        },
        weekChangeRate() {
            const v = this.overview.week_change_rate;
            if (v === null || v === undefined) return "--";
            // UI 优化：|环比| ≥999% 说明基数极小、比例失真，封顶显示避免误导
            if (Math.abs(v) >= 999) return (v > 0 ? "+" : "−") + "≥999";
            return (v > 0 ? "+" : "") + v;
        },
        weekChangeArrow() {
            const v = this.overview.week_change_rate;
            if (v === null || v === undefined) return "";
            if (v > 0) return "↑";
            if (v < 0) return "↓";
            return "→";
        },
        weekChangeDirection() {
            const v = this.overview.week_change_rate;
            if (v === null || v === undefined) return "";
            if (v > 0) return "kpi-up";
            if (v < 0) return "kpi-down";
            return "";
        },
        // --- 口碑反转（D10 拆卡）：翻车帖(pos2neg + other 评论负面) / 护车帖(neg2pos + other 评论正面) ---
        // other = 帖中性：按 comment_sentiment 归位（genuine_sentiment 来自 comment_summary）
        // 同向按评论数倒序，各自 cap=5（卡片超视口会触发全局 resize 监听 mid-render 崩 echarts）
        reversalPosts() {
            const order = { pos2neg: 0, neg2pos: 1, other: 2 };
            return [...this.controversialPosts]
                .sort((a, b) => (order[a.direction] ?? 3) - (order[b.direction] ?? 3)
                    || (b.comment_count || 0) - (a.comment_count || 0));
        },
        reversalFlipPosts() {
            return this.reversalPosts
                .filter(p => p.direction === 'pos2neg' ||
                    (p.direction === 'other' && p.comment_sentiment === 'negative'))
                .slice(0, 5);
        },
        reversalDefendPosts() {
            return this.reversalPosts
                .filter(p => p.direction === 'neg2pos' ||
                    (p.direction === 'other' && p.comment_sentiment === 'positive'))
                .slice(0, 5);
        },
    },
    async mounted() {
        await this.fetchVehicles();
        // P1-1：首屏自动选第一个 active 车，避免空白
        if (!this.currentVehicleId && this.vehicles.length) {
            const first = this.vehicles.find(v => v.status === "active") || this.vehicles[0];
            if (first) {
                this.currentVehicleId = first.id;
                // N-2：回填搜索框（原 H1 显示车名但搜索框空）
                this.searchQuery = `${first.name} (${first.brand})`;
                this.onVehicleChange();
            }
        }
        window.addEventListener("resize", () => {
            this.attentionChart?.resize();
            this.sentimentChart?.resize();
            this.platformChart?.resize();
            this.dimPosChart?.resize();   // UI 优化：维度图拆两实例
            this.dimNegChart?.resize();
            this.sentimentDonutChart?.resize();
            this.commentSentimentDonutChart?.resize();
            // §11.3：词云是自绘 canvas（非 echarts 实例），resize 时直接重绘
            // 2026-10-20：数据源改为分平台词云，当前 tab 有词才重绘
            if ((this.platformWordClouds[this.wcTab] || []).length) {
                this.$nextTick(() => this.renderWordCloud());
            }
        });
        // P1-5：Esc 关闭弹窗/面板/溢出菜单
        window.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                this.showAddModal = false;
                this.showWatchlist = false;
                this.showOverflow = false;
                this.showAllPosts = false;
                this.showReportPanel = false;
                this.expandedReport = null;
                this.postDetailOpen = false;  // I-3：Esc 关帖子详情
            }
        });
        // P2-8：click-outside 关闭溢出菜单（延迟到下一 tick，避免与 ⋮ 按钮
        // 的 @click 同 dispatch 冲突导致菜单打不开）
        window.addEventListener("click", (e) => {
            if (this.showOverflow && !e.target.closest('.dropdown-menu') && !e.target.closest('.icon-btn')) {
                this.showOverflow = false;
            }
        });
        // D2：跨会话恢复 fleetCollecting（mounted 末尾，不阻塞首屏）
        this._restoreFleetState();
    },
    methods: {
        // --- URL scheme 过滤（§11.3 L3 替代项）---
        // postDetail.url 来自采集器，过滤 javascript: 等伪协议
        safeUrl(url) {
            if (!url) return '';
            if (/^javascript:/i.test(url) || /^data:/i.test(url)) return '';
            return url;
        },

        // --- 文本清洗 ---
        // 社媒源（微博/小红书）采集的 title 含 HTML 标签（如 <span class="url-icon">[偷乐]</span>）
        // 直接用 v-text 会显示源码，用 v-html 又会触发 XSS + 外部图片加载失败
        // 解法：strip 所有标签，img 的 alt 文字保留（emoji 兜底）
        stripHtml(html) {
            if (!html) return '';
            const tmp = document.createElement('div');
            tmp.innerHTML = html;
            // 把 <img alt="..."> 替换为 [alt 文字]
            tmp.querySelectorAll('img').forEach(img => {
                const alt = img.getAttribute('alt') || '';
                img.replaceWith(document.createTextNode(alt));
            });
            return (tmp.textContent || '').trim();
        },
        // --- API & Toast 基础设施 ---
        // silent=true 抑制 toast：轮询/搜索联想等高频后台调用失败时不应刷屏
        async apiFetch(url, { json, silent = false, ...opts } = {}) {
            if (json !== undefined) {
                opts.body = JSON.stringify(json);
                opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
            }
            // 挂载路径适配（嵌入 Prism 用）：页面位于 /sentiment-board/ 时，绝对路径
            // /api/* 会打到 Prism 根（无该路由）。改为相对路径，由浏览器按当前文档
            // 基址解析 → 嵌入时 /sentiment-board/api/*，独立运行于 / 时 /api/*（行为不变）。
            // 保留原有 fetch/错误处理逻辑，仅在发起请求前做前缀剥离。
            const reqUrl = (typeof url === 'string' && url.startsWith('/') && !url.startsWith('//'))
                ? url.slice(1) : url;
            try {
                const resp = await fetch(reqUrl, opts);
                if (!resp.ok) { if (!silent) this.showToast(`请求失败 (${resp.status})`); return null; }
                const text = await resp.text();
                try { return JSON.parse(text); }
                catch { if (!silent) this.showToast("响应解析失败"); return null; }
            } catch (e) {
                if (!silent) this.showToast(`网络错误: ${e.message}`);
                return null;
            }
        },
        showToast(msg, type = "error") {
            const id = Date.now() + Math.random();
            this.toasts.push({ id, msg, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 3000);
        },

        // --- Time Range ---
        applyPreset(p) {
            const scrollY = window.scrollY;
            if (p.days === 0) {
                this.rangeStart = "2020-01-01";
            } else {
                this.rangeStart = new Date(Date.now() - p.days * 86400000).toISOString().slice(0, 10);
            }
            this.rangeEnd = new Date().toISOString().slice(0, 10);
            if (this.currentVehicleId) this.onVehicleChange();
            this.$nextTick(() => window.scrollTo(0, scrollY));
        },
        isPresetActive(p) {
            if (p.days === 0) return this.rangeStart === "2020-01-01";
            const expected = new Date(Date.now() - p.days * 86400000).toISOString().slice(0, 10);
            return this.rangeStart === expected && this.rangeEnd === new Date().toISOString().slice(0, 10);
        },

        // --- Vehicles ---
        async fetchVehicles() {
            this.vehicles = await this.apiFetch("/api/vehicles") || [];
        },
        onNewVehicleNameInput() {
            const name = this.newVehicle.name;
            if (!name) return;
            const brandMap = {
                "比亚迪": ["元", "宋", "唐", "秦", "汉", "海豚", "海豹", "海鸥", "驱逐舰", "护卫舰", "腾势", "方程豹"],
                "长安": ["逸动", "UNI", "CS", "深蓝", "阿维塔", "长安Lumin"],
                "吉利": ["星瑞", "星越", "博越", "帝豪", "银河", "极氪", "领克", "几何"],
                "奇瑞": ["艾瑞泽", "瑞虎", "星途", "iCAR", "智界"],
                "长城": ["哈弗", "坦克", "魏牌", "欧拉", "长城炮"],
                "广汽": ["传祺", "埃安", "昊铂"],
                "小鹏": ["小鹏"],
                "蔚来": ["蔚来", "ET", "ES", "EC"],
                "理想": ["理想", "L6", "L7", "L8", "L9", "MEGA"],
                "问界": ["问界", "AITO"],
                "零跑": ["零跑", "C01", "C11", "C10", "T03"],
                "极氪": ["极氪"],
                "领克": ["领克"],
                "宝骏": ["宝骏", "云朵"],
                "上汽": ["荣威", "名爵", "飞凡", "智己"],
                "一汽": ["红旗", "奔腾", "ID"],
                "东风": ["岚图", "风神", "纳米"],
                "北汽": ["极狐", "北京", "BEIJING"],
                "宝马": ["宝马", "i3", "iX", "i4"],
                "奔驰": ["奔驰", "EQ"],
                "奥迪": ["奥迪", "Q4", "Q5", "e-tron"],
                "丰田": ["凯美瑞", "卡罗拉", "RAV4", "汉兰达", "赛那", "bZ"],
                "本田": ["雅阁", "思域", "CR-V", "皓影", "型格"],
                "大众": ["朗逸", "帕萨特", "迈腾", "途观", "ID"],
                "特斯拉": ["Model 3", "Model Y", "Model S", "Model X"],
            };
            for (const [brand, prefixes] of Object.entries(brandMap)) {
                if (prefixes.some(p => name.startsWith(p) || name.includes(p))) {
                    if (!this.newVehicle.brand) this.newVehicle.brand = brand;
                    break;
                }
            }
            if (!this.newVehicle.search_keywords) {
                this.newVehicle.search_keywords = name;
            }
            // 汽车之家车系联想（A+B：强制从真实车系选，防"铂智3X 填成铂金"类错误）
            clearTimeout(this._suggestTimer);
            if (!name) { this.suggestResults = []; this.suggestHighlight = -1; return; }
            this._suggestTimer = setTimeout(async () => {
                const r = await this.apiFetch(`/api/vehicles/suggest?q=${encodeURIComponent(name)}`, {silent: true});
                this.suggestResults = r || [];
                this.suggestHighlight = -1;  // U-7：结果变化重置高亮
            }, 300);
        },
        // U-7：搜索框键盘导航
        onSuggestKeydown(e) {
            if (e.isComposing || this.imeComposing) return;  // N-5：IME 组合态不拦截按键
            if (!this.suggestResults.length) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.suggestHighlight = Math.min(this.suggestHighlight + 1, this.suggestResults.length - 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.suggestHighlight = Math.max(this.suggestHighlight - 1, -1);
            } else if (e.key === 'Enter' && this.suggestHighlight >= 0) {
                e.preventDefault();
                this.selectSuggestion(this.suggestResults[this.suggestHighlight]);
            }
        },
        selectSuggestion(s) {
            // 选中真实车系 → 规范名/品牌/关键词自动填（用户不用手填）
            this.newVehicle.name = s.name;
            this.newVehicle.brand = s.brand;
            this.newVehicle.search_keywords = s.name;
            this.suggestResults = [];
        },
        async addVehicle() {
            if (this.imeComposing) return;  // N-5：IME 组合态不提交
            const kw = this.newVehicle.search_keywords
                ? this.newVehicle.search_keywords.split(",").map(s => s.trim()).filter(Boolean)
                : undefined;
            const created = await this.apiFetch("/api/vehicles", {
                method: "POST",
                json: { ...this.newVehicle, search_keywords: kw },
            });
            if (!created) return;
            this.showAddModal = false;
            this.newVehicle = { name: "", brand: "", search_keywords: "" };
            this.suggestResults = [];
            await this.fetchVehicles();
            this.currentVehicleId = created.id;
            this.searchQuery = `${created.name} (${created.brand})`;
            await this.onVehicleChange();
        },

        // --- Core data loading ---
        async onVehicleChange() {
            if (!this.currentVehicleId) return;
            // §11.2 竞态守卫：递增 token，回调比对丢弃旧请求结果
            const token = (this._vehicleChangeToken = (this._vehicleChangeToken || 0) + 1);
            // P2-5：清采集轮询 + 复位 loading/refreshing（轮询 URL 按 currentVehicleId
            // 取值，不清会漂移到新车且 loading 永卡；refreshing 残留会拦全车采集 +
            // 下次轮询终态误走 _onRefreshCompleted）；下方若新车仍有活跃 phase 会恢复轮询
            if (this.pipelinePollTimer) { clearInterval(this.pipelinePollTimer); this.pipelinePollTimer = null; }
            this.loading = false;
            this.pipelinePhase = "";
            this.refreshing = false;
            window.scrollTo(0, 0);  // P1-9：切车回顶部
            this.loadingVehicle = true;  // P1-6：切车加载遮罩
            this.showAllPosts = false;
            this.expandedReport = null;
            this.reportContent = "";
            this.eventTab = "all";
            this.hotPostsTab = "douyin";
            this.postsFilter = { sentiment: "", platform: "" };  // R-2：重置保持对象类型（非字符串）
            // 2026-10-20 竞态收口：缺陷簇是 fire-and-forget 秒级 LLM 请求，切车
            // 不复位会短暂显示上一辆车的簇（T7 看板画上 T11 簇实证）；loadDefectThemes
            // 另有 token 守卫双保险
            this.defectThemes = [];
            this.defectLoading = false;
            try {
            await Promise.all([
                this.loadOverview(),
                this.loadTrend(),
                this.loadCommentSentimentOverview(),
                this.loadSentimentTrend(),
                this.loadCommentSentimentTrend(),
                this.loadDimSentiment(),
                this.loadEventTimeline(),
                this.loadPlatformDist(),
                this.loadTopPosts(),
                this.loadNegativeRadar(),
                this.loadCollectionStatus(),
                this.apiFetch(`/api/vehicles/${this.currentVehicleId}/progress`, { silent: true }).then(pd => { this.collectionProgress = pd || {}; }),
                this.loadWordCloud(),
                this.loadPosts(1),
                this.loadControversialPosts(),
                this.loadWatchItems(),
            ]);
            // 竞态守卫：若期间又切了车，本次结果丢弃，不渲染
            if (token !== this._vehicleChangeToken) return;
            this.renderAllCharts();
            // P2-5 续：切到的车若有活跃采集/刷新，恢复轮询（终态由 _pollPipeline 复位）
            const activePh = this.collectionProgress?.overall_phase;
            if (["collecting", "enriching", "analyzing", "calculating", "refreshing"].includes(activePh)) {
                this._startPolling();
            }
            // 缺陷簇挖掘背后是 LLM 调用（秒级），不阻塞首屏——fire-and-forget
            this.loadDefectThemes();
            // 7天增量视图（D13）：仅增量模式时调，不阻塞首屏
            this.loadIncrementOverview();
            // T6.3：历史报告面板加载存量报告（之前恒显示"暂无报告"）
            this.loadReports();
            } finally { if (token === this._vehicleChangeToken) this.loadingVehicle = false; }  // P1-6：移除遮罩
        },

        renderAllCharts() {
            this.$nextTick(() => {
                this.renderSentimentDonut();
                this.renderCommentSentimentDonut();
                this.renderAttentionChart();
                this.renderSentimentChart();
                this.renderDimChart();
                this.renderPlatformChart();
                this.renderWordCloud();
            });
        },

        renderSentimentDonut() {
            const el = document.getElementById("sentiment-donut");
            if (!el) return;
            if (!this.sentimentTotal) {
                this.sentimentDonutChart && this.sentimentDonutChart.dispose(); this.sentimentDonutChart = null;
                this._markChartEmpty(el);
                return;
            }
            this._clearChartEmpty(el);
            if (!this.sentimentDonutChart) {
                this.sentimentDonutChart = Vue.markRaw(echarts.init(el));
            }
            this.sentimentDonutChart.setOption({
                tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
                series: [{
                    type: "pie",
                    radius: ["50%", "78%"],
                    center: ["50%", "50%"],
                    avoidLabelOverlap: false,
                    itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 2 },
                    label: { show: false },
                    emphasis: { label: { show: true, fontSize: 16, fontWeight: "bold" } },
                    data: [
                        { value: this.overview.positive || 0, name: "正面", itemStyle: { color: CHART_COLORS.pos } },
                        { value: this.overview.negative || 0, name: "负面", itemStyle: { color: CHART_COLORS.neg } },
                        { value: this.overview.neutral || 0, name: "中性", itemStyle: { color: CHART_COLORS.neu } },
                    ],
                }],
            }, true);
        },

        renderCommentSentimentDonut() {
            const el = document.getElementById("comment-sentiment-donut");
            if (!el) return;
            const total = this.commentSentimentOverview?.total || 0;
            if (!total) {
                this.commentSentimentDonutChart && this.commentSentimentDonutChart.dispose(); this.commentSentimentDonutChart = null;
                this._markChartEmpty(el);
                return;
            }
            this._clearChartEmpty(el);
            if (!this.commentSentimentDonutChart) {
                this.commentSentimentDonutChart = Vue.markRaw(echarts.init(el));
            }
            this.commentSentimentDonutChart.setOption({
                tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
                series: [{
                    type: "pie",
                    radius: ["50%", "78%"],
                    center: ["50%", "50%"],
                    avoidLabelOverlap: false,
                    itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 2 },
                    label: { show: false },
                    emphasis: { label: { show: true, fontSize: 16, fontWeight: "bold" } },
                    data: [
                        { value: this.commentSentimentOverview.positive || 0, name: "正面", itemStyle: { color: CHART_COLORS.pos } },
                        { value: this.commentSentimentOverview.negative || 0, name: "负面", itemStyle: { color: CHART_COLORS.neg } },
                        { value: this.commentSentimentOverview.neutral || 0, name: "中性", itemStyle: { color: CHART_COLORS.neu } },
                    ],
                }],
            }, true);
        },
        // --- API loaders ---
        async loadOverview() {
            this.overview = await this.apiFetch(`/api/dashboard/overview/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || {};
        },
        async loadTrend() {
            this.trendData = await this.apiFetch(`/api/dashboard/trend/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || {};
        },
        async loadCommentSentimentOverview() {
            this.commentSentimentOverview = await this.apiFetch(
                `/api/dashboard/comment-sentiment-overview/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`
            ) || {};
        },
        async loadSentimentTrend() {
            this.sentimentTrendData = await this.apiFetch(`/api/dashboard/sentiment-trend/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || [];
        },
        async loadCommentSentimentTrend() {
            // T1.5: 评论级情感趋势——负面声量曲线数据源（替代帖级 sentimentTrendData）
            this.commentSentimentTrendData = await this.apiFetch(
                `/api/dashboard/comment-sentiment-trend/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`
            ) || [];
        },
        async loadDimSentiment() {
            this.dimSentiment = await this.apiFetch(`/api/dashboard/dim-sentiment/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || [];
        },
        async loadEventTimeline() {
            // 2026-10-20：彻底剔除新闻事件（source=social），新闻源已停采且不属于社媒发酵口径
            this.eventTimeline = await this.apiFetch(`/api/dashboard/vehicles/${this.currentVehicleId}/events?start=${this.rangeStart}&end=${this.rangeEnd}&source=social`) || [];
        },
        async loadPlatformDist() {
            this.platformDist = await this.apiFetch(`/api/dashboard/platform-distribution/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || [];
        },
        async loadTopPosts() {
            // start/end 跟随用户窗（coalesce(published_at, collected_at) 兜底 NULL，
            // 微博/抖音 published_at 常 NULL 不再丢帖）
            const params = new URLSearchParams({ limit: "10", start: this.rangeStart, end: this.rangeEnd });
            if (this.hotPostsTab === 'negative') params.set('sentiment', 'negative');
            else if (this.hotPostsTab && this.hotPostsTab !== 'all') params.set('platform', this.hotPostsTab);
            this.topPosts = await this.apiFetch(`/api/dashboard/top-posts/${this.currentVehicleId}?${params}`) || [];
        },
        async switchHotTab(key) {
            if (this.hotPostsTab === key) return;
            this.hotPostsTab = key;
            this.loadTopPosts();
        },
        async loadCollectionStatus() {
            const statuses = await this.apiFetch(`/api/vehicles/${this.currentVehicleId}/collection-status`);
            if (!statuses) { this.lastCollectionTime = ""; return; }
            const all = statuses.find(s => s.source === "all");
            // 方案 C：显示 max(last_collected_at, last_refreshed_at)（NULL 兼容）
            const collected = all && all.last_collected_at ? all.last_collected_at : "";
            const refreshed = all && all.last_refreshed_at ? all.last_refreshed_at : "";
            const latest = refreshed > collected ? refreshed : collected;
            this.lastCollectionTime = latest ? latest.substring(0, 16).replace("T", " ") : "";
        },
        async loadPosts(page) {
            const params = new URLSearchParams({ page, size: this.posts.size });
            if (this.postsFilter.sentiment) params.set("sentiment", this.postsFilter.sentiment);
            if (this.postsFilter.platform) params.set("platform", this.postsFilter.platform);
            params.set("start", this.rangeStart);
            params.set("end", this.rangeEnd);
            this.posts = await this.apiFetch(`/api/dashboard/posts/${this.currentVehicleId}?${params}`)
                || { items: [], total: 0, page: 1, size: this.posts.size };
        },
        async loadWordCloud() {
            // 2026-10-20：按平台分别取词云（同一口径，不另起统计）
            const base = `/api/dashboard/word-cloud/${this.currentVehicleId}?limit=80&start=${this.rangeStart}&end=${this.rangeEnd}`;
            const [dy, xhs, cz] = await Promise.all([
                this.apiFetch(`${base}&platform=douyin`),
                this.apiFetch(`${base}&platform=xiaohongshu`),
                this.apiFetch(`${base}&platform=chezhiwang`),
            ]);
            this.platformWordClouds = {
                douyin: dy || [],
                xiaohongshu: xhs || [],
                chezhiwang: cz || [],
            };
            this.wordCloudData = [...(dy || []), ...(xhs || []), ...(cz || [])];
            this.$nextTick(() => this.renderWordCloud());
        },
        switchWcTab(key) {
            if (this.wcTab === key) return;
            this.wcTab = key;
            this.$nextTick(() => this.renderWordCloud());
        },
        async loadReports() {
            this.reports = await this.apiFetch(`/api/dashboard/reports/${this.currentVehicleId}`) || [];
        },
        async loadControversialPosts() {
            this.controversialPosts = await this.apiFetch(`/api/dashboard/comment-sentiment-diff/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || [];
        },

        // --- 负面雷达 ---
        async loadNegativeRadar() {
            this.negativeRadar = await this.apiFetch(
                `/api/dashboard/negative-radar/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`
            ) || {};
        },

        // --- 关注清单（手动标记，无状态机） ---
        async loadWatchItems() {
            if (!this.currentVehicleId) return;
            this.watchItems = await this.apiFetch(`/api/watchlist/${this.currentVehicleId}`) || [];
        },
        async addWatch(payload) {
            if (!this.currentVehicleId) return;
            const r = await this.apiFetch(`/api/watchlist/${this.currentVehicleId}`, {
                method: "POST", json: payload,
            });
            if (r) {
                if (r.duplicate) { this.showToast("已关注过", "ok"); }  // U-1：已关注回显
                else { await this.loadWatchItems(); this.showToast("已加入关注", "ok"); }
            }
        },
        isWatched(postUrl) {  // U-1：★ 按钮已关注状态
            return this.watchItems.some(w => w.source_ref === postUrl);
        },
        async removeWatch(id) {
            await this.apiFetch(`/api/watchlist/${this.currentVehicleId}/${id}`, {method: "DELETE"});
            await this.loadWatchItems();
        },
        sourceTypeLabel(t) {
            return {hot_post:"热帖", complaint:"吐槽", defect_cluster:"缺陷簇", event:"事件"}[t] || t;
        },
        todayStr() { return new Date().toISOString().slice(0,10); },

        // --- 缺陷话题簇（3.x 话题发酵） ---
        async loadDefectThemes() {
            if (!this.currentVehicleId) return;
            // 2026-10-20 竞态守卫：缺陷簇背后是秒级 LLM 重算，切车后旧响应晚到
            // 会覆盖新车的簇（用户实证 T7 看板显示 T11 簇）——token 比对丢弃。
            // 参数已退役：后端统一 30 天权威窗，不再跟随全局日期范围（防窗口互踩）
            const token = this._vehicleChangeToken;
            this.defectLoading = true;
            try {
                const data = await this.apiFetch(`/api/dashboard/defect-themes/${this.currentVehicleId}`) || [];
                if (token !== this._vehicleChangeToken) return;  // 已切车，丢弃旧响应
                this.defectThemes = data;
            } finally {
                if (token === this._vehicleChangeToken) this.defectLoading = false;
            }
        },
        // --- 7天增量视图（D13）---
        async loadIncrementOverview() {
            if (!this.currentVehicleId || !this.isIncrementMode) return;
            this.incrementLoading = true;
            try {
                this.incrementOverview = await this.apiFetch(
                    `/api/dashboard/increment-overview/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`
                ) || {};
            } finally {
                this.incrementLoading = false;
            }
        },
        severityLabel(s) {
            return {high:"高严重", mid:"中", low:"低"}[s] || s;
        },
        // 3.1 发酵话题追踪：起止跨度（含首尾两天），缺日期返回 '--'
        eventDurationDays(e) {
            if (!e || !e.start_date || !e.end_date) return '--';
            const s = new Date(e.start_date + 'T00:00:00'), t = new Date(e.end_date + 'T00:00:00');
            if (isNaN(s) || isNaN(t)) return '--';
            const days = Math.round((t - s) / 864e5) + 1;
            return days > 0 ? days : '--';
        },
        // --- Charts ---
        // UI 优化：图表空态统一——套 .empty 样式并纵向居中，替代裸 textContent="暂无数据"
        _markChartEmpty(el, msg = "暂无数据") {
            if (!el) return;
            el.classList.add("empty", "chart-empty");
            el.textContent = msg;
        },
        _clearChartEmpty(el) {
            if (el) el.classList.remove("empty", "chart-empty");
        },
        renderAttentionChart() {
            const el = document.getElementById("attention-chart");
            if (!el) return;
            const raw = this.trendData?.data || this.trendData;
            if (!raw || !raw.length) {
                this.attentionChart && this.attentionChart.clear();
                this._markChartEmpty(el);
                return;
            }
            this._clearChartEmpty(el);
            if (!this.attentionChart) this.attentionChart = Vue.markRaw(echarts.init(el));

            // 2026-10-20：拆为抖音 / 小红书两条搜索指数曲线
            // search_detail 是各平台原始量纲（抖音量级远高于小红书），
            // 故按各平台自身最大值归一化到 0-100 后同轴对比，避免一条线被压平
            const PLAT_KEY = { douyin: 'douyin', dy: 'douyin', xiaohongshu: 'xiaohongshu', xhs: 'xiaohongshu' };
            const COLOR = { douyin: '#3a6ea5', xiaohongshu: CHART_COLORS.accent };
            const srcMax = { douyin: 0, xiaohongshu: 0 };
            raw.forEach(d => {
                Object.entries(d.search_detail || {}).forEach(([k, v]) => {
                    const key = PLAT_KEY[String(k).toLowerCase()];
                    const n = Number(v) || 0;
                    if (key && n > srcMax[key]) srcMax[key] = n;
                });
            });

            const buckets = {};
            raw.forEach(d => {
                const dt = new Date(d.date);
                const day = dt.getDay();
                const weekStart = new Date(dt);
                weekStart.setDate(dt.getDate() - day);
                const key = weekStart.getFullYear() + '-' + String(weekStart.getMonth()+1).padStart(2,'0') + '-' + String(weekStart.getDate()).padStart(2,'0');  // P2-1 本地日期避免 toISOString 东八区回退
                if (!buckets[key]) buckets[key] = { dy: 0, dyN: 0, xhs: 0, xhsN: 0, dyRaw: 0, xhsRaw: 0 };
                const b = buckets[key];
                Object.entries(d.search_detail || {}).forEach(([k, v]) => {
                    const p = PLAT_KEY[String(k).toLowerCase()];
                    const n = Number(v) || 0;
                    if (!p || n <= 0 || !srcMax[p]) return;
                    if (p === 'douyin') { b.dy += Math.min(n / srcMax.douyin, 1) * 100; b.dyN += 1; b.dyRaw += n; }
                    else { b.xhs += Math.min(n / srcMax.xiaohongshu, 1) * 100; b.xhsN += 1; b.xhsRaw += n; }
                });
            });
            const weekKeys = Object.keys(buckets).sort().slice(-12);  // U-3：统一 12 周跨度
            const dySeries = weekKeys.map(k => buckets[k].dyN ? Math.round(buckets[k].dy / buckets[k].dyN) : null);
            const xhsSeries = weekKeys.map(k => buckets[k].xhsN ? Math.round(buckets[k].xhs / buckets[k].xhsN) : null);

            // 峰值标注：每个平台取自身最高周，pin 内显示该周事件数，完整话题走 tooltip 与图下结论
            const annotations = this.trendData?.event_annotations || {};
            const peakMark = data => {
                let mi = -1, mv = -1;
                data.forEach((v, i) => { if (v !== null && v > mv) { mv = v; mi = i; } });
                if (mi < 0) return [];
                const tags = annotations[weekKeys[mi]] || [];
                if (!tags.length) return [];
                return [{ coord: [weekKeys[mi], mv], value: tags.length }];
            };
            const mkSeries = (name, data, color) => ({
                name, type: 'line', data, smooth: true, symbol: 'circle', symbolSize: 4, connectNulls: true,
                lineStyle: { color, width: 2.2 }, itemStyle: { color },
                areaStyle: color === CHART_COLORS.accent
                    ? { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: color + '26' }, { offset: 1, color: color + '04' }] } }
                    : undefined,
                markPoint: { data: peakMark(data), symbol: 'pin', symbolSize: 32, itemStyle: { color: '#c0392b' }, label: { show: true, fontSize: 10, color: '#fff', position: 'inside' } },
            });

            this.attentionChart.setOption({
                legend: { data: ['抖音', '小红书'], right: 8, top: 0, itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 11, color: CHART_COLORS.muted } },
                tooltip: { trigger: "axis", formatter: p => {
                    const idx = p[0].dataIndex;
                    const b = buckets[weekKeys[idx]] || {};
                    let html = `${weekKeys[idx]}`;
                    if (b.dyN) html += `<br/>抖音：${Math.round(b.dyRaw / b.dyN)}（相对 ${Math.round(b.dy / b.dyN)}）`;
                    if (b.xhsN) html += `<br/>小红书：${Math.round(b.xhsRaw / b.xhsN)}（相对 ${Math.round(b.xhs / b.xhsN)}）`;
                    // V-1：tooltip 显示该周事件标签
                    const tags = annotations[weekKeys[idx]] || [];
                    if (tags.length) html += `<br/>📍 ${tags.join('、')}`;
                    return html;
                }},
                grid: { top: 34, right: 30, bottom: 32, left: 48 },
                xAxis: { type: "category", data: weekKeys, boundaryGap: false, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11 } },
                yAxis: { type: "value", min: 0, max: 100, name: "相对热度", nameTextStyle: { color: CHART_COLORS.muted, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: CHART_COLORS.grid } }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11 } },
                series: [mkSeries('抖音', dySeries, COLOR.douyin), mkSeries('小红书', xhsSeries, COLOR.xiaohongshu)],
            }, false);
        },

        // 图表粒度自适应：按当前时间窗跨度决定分桶粒度
        // ≤14 天 → 日粒度（每日一个点，短期波动可见）；>14 天 → ISO 周粒度（压缩噪点）
        // 注意：用 rangeStart/rangeEnd 而非数据首尾，让用户切窗立即影响粒度
        _chartGranularity() {
            const days = (new Date(this.rangeEnd) - new Date(this.rangeStart)) / 86400000;
            return days <= 14 ? 'day' : 'week';
        },
        // 情感趋势分桶 key：日粒度直接用日期；周粒度取 ISO 周一日期
        _sentimentBucketKey(dateStr, granularity) {
            if (granularity === 'day') return dateStr;
            const dt = new Date(dateStr + 'T00:00:00');
            const day = dt.getDay();  // P2-1：统一周日起（与搜索热度/讨论图对齐）
            const weekStart = new Date(dt);
            weekStart.setDate(dt.getDate() - day);
            // P2-1：用本地日期格式，避免 toISOString 东八区回退一天
            return weekStart.getFullYear() + '-' + String(weekStart.getMonth() + 1).padStart(2, '0') + '-' + String(weekStart.getDate()).padStart(2, '0');
        },
        renderSentimentChart() {
            const el = document.getElementById("sentiment-chart");
            if (!el) return;
            if (!this.sentimentTrendData || !this.sentimentTrendData.length) {
                this.sentimentChart && this.sentimentChart.clear();
                this._markChartEmpty(el);
                return;
            }
            this._clearChartEmpty(el);
            if (!this.sentimentChart) this.sentimentChart = Vue.markRaw(echarts.init(el));

            // 粒度自适应：跨度 ≤14 天按日分桶，否则按 ISO 周分桶（周一起）
            const granularity = this._chartGranularity();
            const buckets = {};
            this.sentimentTrendData.forEach(d => {
                const key = this._sentimentBucketKey(d.date, granularity);
                if (!buckets[key]) buckets[key] = { positive: 0, negative: 0, neutral: 0 };
                buckets[key].positive += d.positive || 0;
                buckets[key].negative += d.negative || 0;
                buckets[key].neutral += d.neutral || 0;
            });
            const allKeys = Object.keys(buckets).sort();
            // 日粒度取近 14 点、周粒度取近 12 点（U-3 统一）
            const keys = allKeys.slice(granularity === 'day' ? -14 : -12);  // U-3：统一 12 周
            const positives = keys.map(k => buckets[k].positive);
            const neutrals = keys.map(k => buckets[k].neutral);
            const negatives = keys.map(k => buckets[k].negative);

            // change2 块A 并₁：负面声量趋势并入本图——评论级负面占比线（原独立卡退役）。
            // 与柱同 key 分桶（评论序列缺日 → null 断点，不造 0）
            const cbuckets = {};
            (this.commentSentimentTrendData || []).forEach(d => {
                const key = this._sentimentBucketKey(d.date, granularity);
                if (!cbuckets[key]) cbuckets[key] = { positive: 0, negative: 0, neutral: 0 };
                cbuckets[key].positive += d.positive || 0;
                cbuckets[key].negative += d.negative || 0;
                cbuckets[key].neutral += d.neutral || 0;
            });
            const rates = keys.map(k => {
                const b = cbuckets[k];
                if (!b) return null;
                const total = b.positive + b.negative + b.neutral;
                return total ? +(b.negative / total * 100).toFixed(1) : 0;
            });

            this.sentimentChart.setOption({
                tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: ps => {
                    const i = ps[0].dataIndex;
                    let html = `${ps[0].axisValue}<br/>帖：正 ${positives[i]} · 中 ${neutrals[i]} · 负 ${negatives[i]}`;
                    const r = rates[i];
                    if (r !== null && r !== undefined) html += `<br/>评论负面占比: ${r}%`;
                    return html;
                }},
                legend: { data: ["正面", "中性", "负面", "评论负面占比"], bottom: 0, itemWidth: 8, itemHeight: 8, textStyle: { color: CHART_COLORS.muted, fontSize: 11 } },
                grid: { top: 16, right: 48, bottom: 36, left: 48 },
                xAxis: { type: "category", data: keys, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: CHART_COLORS.grid } }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11 } },
                yAxis: [
                    { type: "value", name: "帖数", axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: CHART_COLORS.grid } }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11 } },
                    { type: "value", name: "占比", min: 0, max: value => Math.max(10, Math.ceil((value.max * 1.25) / 5) * 5), axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11, formatter: '{value}%' } },
                ],
                series: [
                    { name: "正面", type: "bar", stack: "s", data: positives, itemStyle: { color: CHART_COLORS.pos }, barWidth: "50%" },
                    { name: "中性", type: "bar", stack: "s", data: neutrals, itemStyle: { color: CHART_COLORS.neu } },
                    { name: "负面", type: "bar", stack: "s", data: negatives, itemStyle: { color: CHART_COLORS.neg, borderRadius: [4, 4, 0, 0] } },
                    { name: "评论负面占比", type: "line", yAxisIndex: 1, data: rates, smooth: true, symbol: "circle", symbolSize: 3, connectNulls: true, lineStyle: { color: hexToRgba(CHART_COLORS.accent, 0.6), width: 1.4, type: "dashed" }, itemStyle: { color: hexToRgba(CHART_COLORS.accent, 0.6) } },
                ],
            }, false);
        },

        renderDimChart() {
            // UI 优化：原「左=正向得分 / 右=负面占比」同行分叉条，两种量纲不同易被读成同一指标
            // → 拆为上下两张独立小图：上=帖侧正面得分(0~1)，下=评论侧负面占比(0~100%)。
            // 两图共用同一维度顺序（按正向得分升序，低分在前），逐行可对照。
            // 保留原数据装配逻辑：posMap=dimSentiment（帖子侧 GLM 维度分）；negMap=negativeRadar.negative_dims（评论侧）。
            const elPos = document.getElementById("dim-chart-pos");
            const elNeg = document.getElementById("dim-chart-neg");
            if (!elPos || !elNeg) return;
            const posMap = {};
            (this.dimSentiment || []).forEach(d => { posMap[d.dim] = d.score; });
            const negMap = {};
            ((this.negativeRadar && this.negativeRadar.negative_dims) || []).forEach(d => {
                if (d.negative_rate != null) negMap[d.dim] = d.negative_rate;
            });
            const dims = [...new Set([...Object.keys(posMap), ...Object.keys(negMap)])];
            if (!dims.length) {
                this.dimPosChart && this.dimPosChart.dispose(); this.dimPosChart = null;
                this.dimNegChart && this.dimNegChart.dispose(); this.dimNegChart = null;
                this._markChartEmpty(elPos, "暂无维度数据");
                this._markChartEmpty(elNeg);
                return;
            }
            // 排序：按正向得分升序（与原版一致）
            dims.sort((a, b) => (posMap[a] ?? -1) - (posMap[b] ?? -1));
            // 展示维度：先纳入所有“有评论负面数据”的维度，再补正向得分最低的维度，最多 9 行防标签拥挤
            const MAX_DIM = 9;
            const shown = [];
            Object.keys(negMap).forEach(d => { if (!shown.includes(d)) shown.push(d); });
            for (const d of dims) { if (shown.length >= MAX_DIM) break; if (!shown.includes(d)) shown.push(d); }
            shown.sort((a, b) => (posMap[a] ?? -1) - (posMap[b] ?? -1));

            // 正面得分可正可负（GLM 维度分 -1~1）：负分项在 0 线左侧成条，
            // 标签按符号贴条端（负→left / 正→right），避免全部聚集在 0 线
            const posVals = shown.map(d => {
                const v = posMap[d] != null ? +Number(posMap[d]).toFixed(2) : null;
                return { value: v, label: { position: (v != null && v < 0) ? "left" : "right" } };
            });
            const negVals = shown.map(d => (negMap[d] != null ? +Number(negMap[d]).toFixed(2) : null));

            this._clearChartEmpty(elPos); this._clearChartEmpty(elNeg);
            if (!this.dimPosChart) this.dimPosChart = Vue.markRaw(echarts.init(elPos));
            if (!this.dimNegChart) this.dimNegChart = Vue.markRaw(echarts.init(elNeg));

            const baseY = { type: "category", data: shown, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: "#15140f", fontSize: 12 } };

            this.dimPosChart.setOption({
                tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: ps => {
                    const dim = ps[0].axisValue, pv = posMap[dim];
                    return `${dim}<br/>正面得分: ${pv != null ? Number(pv).toFixed(2) : "（无数据）"}`;
                }},
                grid: { top: 8, bottom: 8, left: 112, right: 52 },
                xAxis: { type: "value", min: -1, max: 1, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: CHART_COLORS.grid } }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11 } },
                yAxis: { ...baseY },
                series: [{ name: "正面得分", type: "bar", data: posVals, barWidth: "58%",
                    itemStyle: { color: hexToRgba(CHART_COLORS.pos, 0.8), borderRadius: [0, 4, 4, 0] },
                    label: { show: true, position: "right", formatter: p => (p.value == null ? "—" : Number(p.value).toFixed(2)), color: CHART_COLORS.muted, fontSize: 11, fontFamily: "Inter" } }],
            }, true);

            this.dimNegChart.setOption({
                tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: ps => {
                    const dim = ps[0].axisValue, nv = negMap[dim];
                    return `${dim}<br/>评论负面占比: ${nv != null ? (nv * 100).toFixed(0) + "%" : "（无数据）"}`;
                }},
                grid: { top: 8, bottom: 8, left: 112, right: 52 },
                xAxis: { type: "value", min: 0, max: 1, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: CHART_COLORS.grid } }, axisLabel: { color: CHART_COLORS.muted, fontSize: 11, formatter: v => (v * 100).toFixed(0) + "%" } },
                yAxis: { ...baseY },
                series: [{ name: "评论负面占比", type: "bar", data: negVals, barWidth: "58%",
                    itemStyle: { color: hexToRgba(CHART_COLORS.neg, 0.8), borderRadius: [0, 4, 4, 0] },
                    label: { show: true, position: "right", formatter: p => (p.value == null ? "—" : (p.value * 100).toFixed(0) + "%"), color: CHART_COLORS.muted, fontSize: 11, fontFamily: "Inter" } }],
            }, true);
        },

        renderPlatformChart() {
            const el = document.getElementById("platform-chart");
            if (!el) return;
            if (!this.platformDist || !this.platformDist.length) {
                this.platformChart && this.platformChart.dispose(); this.platformChart = null;
                this._markChartEmpty(el);
                return;
            }
            this._clearChartEmpty(el);
            if (!this.platformChart) this.platformChart = Vue.markRaw(echarts.init(el));
            // 2026-10-20：只展示在采三平台（抖音 / 小红书 / 车质网），微博/快手/新闻已停采不再入图
            const ORDER = ['douyin', 'xiaohongshu', 'chezhiwang'];
            const data = ORDER
                .map(k => this.platformDist.find(d => d.platform === k))
                .filter(Boolean)
                .sort((a, b) => a.count - b.count);
            if (!data.length) {
                this.platformChart && this.platformChart.dispose(); this.platformChart = null;
                this._markChartEmpty(el);
                return;
            }
            const max = Math.max(...data.map(d => d.count), 1);
            this.platformChart.setOption({
                tooltip: {},
                // UI 优化：left 64→92，避免「车质网」等 Y 轴标签被左侧裁切
                grid: { top: 8, right: 40, bottom: 8, left: 92 },
                xAxis: { type: "value", show: false },
                yAxis: { type: "category", data: data.map(d => this.platformLabel(d.platform)), axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: CHART_COLORS.muted, fontSize: 12 } },
                series: [{
                    type: "bar", data: data.map(d => ({ value: d.count, itemStyle: { color: `rgba(201,100,66,${(0.4 + 0.55 * (d.count / max)).toFixed(2)})`, borderRadius: [0, 4, 4, 0] } })),
                    barWidth: "58%",
                    label: { show: true, position: "right", color: CHART_COLORS.muted, fontSize: 11, fontFamily: "Inter" },
                }],
            }, true);
        },

        renderWordCloud() {
            // Canvas 螺旋词云（echarts-wordcloud@2.1.0 不兼容 echarts5，自绘避免依赖）
            // 大词居中、小词螺旋外扩，碰撞检测防重叠，字号 pow 曲线 + 配色梯度 + 透明度
            const el = document.getElementById("word-cloud-main");
            if (!el) return;
            // 2026-10-20：数据源改为「当前 tab 平台」的词云
            const list = (this.platformWordClouds || {})[this.wcTab] || [];
            if (!list.length) { el.innerHTML = `<div class="empty chart-empty" style="height:220px">${this.platformLabel(this.wcTab)}暂无词云</div>`; return; }
            el.style.padding = "0";
            el.innerHTML = '<canvas id="wc-canvas"></canvas>';
            const canvas = document.getElementById("wc-canvas");
            const W = el.offsetWidth || 800, H = 220;
            canvas.width = W; canvas.height = H;
            const ctx = canvas.getContext("2d");
            const data = [...list].filter((d) => {
                // 2026-10-20：剔除车型名/品牌名分词碎片（Model Y → modely / model / modelyl / tesla），
                // 否则词云焦点被车型名本身占满，看不出用户真正的关注点
                const w = String(d.name || "").toLowerCase();
                if (!w) return false;
                const key = ((this.currentVehicleName || "") + (this.currentVehicleBrand || "")).replace(/\s+/g, "").toLowerCase();
                const stem = key.slice(0, 4);
                return !(w.length >= 3 && (key.includes(w) || (stem.length >= 4 && w.includes(stem))));
            }).sort((a, b) => b.value - a.value).slice(0, 60);
            if (!data.length) { el.innerHTML = `<div class="empty chart-empty" style="height:220px">${this.platformLabel(this.wcTab)}暂无词云</div>`; return; }
            const maxV = data[0].value;
            // UI 优化：原紫/粉/绿/橙与全站暖色系冲突 → 收敛为主题色系（accent 家族 + 正/负/中性灰）
            const palette = ["#b85638", "#2348b8", "#9c2a25", "#a44f33", "#3a6ea5", "#c96442", "#5a564e", "#7a7670"];
            const placed = [];
            const cx = W / 2, cy = H / 2;
            const hit = (b) => placed.some(p => !(b.x + b.w < p.x || b.x > p.x + p.w || b.y + b.h < p.y || b.y > p.y + p.h));
            data.forEach((d, i) => {
                const ratio = Math.pow(d.value / maxV, 0.6);
                const size = Math.round(13 + ratio * 28);
                ctx.font = `${ratio > 0.5 ? 600 : 500} ${size}px "PingFang SC", "Microsoft YaHei", sans-serif`;
                const w = ctx.measureText(d.name).width, h = size;
                // UI 优化：用黄金角确定性铺开（原 Math.random 起始角导致每次重绘布局抖动）
                let angle = i === 0 ? 0 : i * 2.399963, r = 0;
                for (let step = 0; step < 600; step++) {
                    const x = cx + Math.cos(angle) * r - w / 2;
                    const y = cy + Math.sin(angle) * r * 0.55 + h / 2;
                    const box = { x: x - 3, y: y - h - 3, w: w + 6, h: h + 6 };
                    // 2026-10-20：补画布边界判定（原只做碰撞检测，贴边词被上下裁切）
                    const inBounds = box.x >= 0 && box.x + box.w <= W && box.y >= 0 && box.y + box.h <= H;
                    if (inBounds && !hit(box)) {
                        placed.push(box);
                        ctx.fillStyle = palette[i % palette.length];
                        ctx.globalAlpha = 0.78 + ratio * 0.22;  // UI 优化：抬高小词透明度（原 0.6 过淡）
                        ctx.fillText(d.name, x, y);
                        ctx.globalAlpha = 1;
                        return;
                    }
                    angle += 0.25; r += 0.6;
                }
            });
        },

        // --- Labels ---
        parseJson(value, fallback) {
            if (!value) return fallback;
            if (typeof value === 'object') return value;
            try { return JSON.parse(value); } catch (e) { return fallback; }
        },
        parsedDimSentiment(raw) {
            const d = this.parseJson(raw, {});
            return Array.isArray(d) ? d : Object.entries(d || {}).map(([k, v]) => ({dim: k, score: v}));
        },
        parsedCommentSummary(raw) {
            return this.parseJson(raw, null);
        },
        // change2 块A D1（R29）：停采平台在分布图标注"（停采）"——历史存量仍展示
        // UI 优化：后缀由"（已停采）"缩短，避免 Y 轴标签过长
        platformLabelStopped(name) {
            const stopped = new Set(["weibo", "wb", "kuaishou", "ks", "news"]);
            return this.platformLabel(name) + (stopped.has(name) ? "（停采）" : "");
        },
        platformLabel(name) {
            // UI 优化：补 chezhiwang→车质网（原缺失导致分布图显示为截断英文 "ezhiwang"）
            const map = { news: "新闻源", xiaohongshu: "小红书", weibo: "微博", douyin: "抖音", kuaishou: "快手", chezhiwang: "车质网", xhs: "小红书", wb: "微博", dy: "抖音", ks: "快手" };
            return map[name] || name;
        },
        sentimentLabel(s) {
            return { positive: "正面", negative: "负面", neutral: "中性", mixed: "混合" }[s] || s;
        },
        reversalLabel(d) {
            return { pos2neg: "🔴 好评翻车", neg2pos: "🟢 差评反转", other: "⚪ 情感错位" }[d] || d;
        },

        // --- Reports ---
        reportTypeLabel(t) {
            return { brief: "事件简报", deep_report: "深度报告", weekly_digest: "周报" }[t] || t;
        },
        reportPreview(content) {
            if (!content) return "";
            const text = content.replace(/[#*_\n]/g, " ").substring(0, 120);
            return text + "...";
        },
        toggleReport(id) {
            this.expandedReport = this.expandedReport === id ? null : id;
        },
        renderMarkdown(text) {
            if (!text) return "";
            // P3-3：先 HTML 转义防 XSS（报告内容源自社媒抓取文本）
            text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            let html = text
                .replace(/^### (.+)$/gm, "<h4>$1</h4>")
                .replace(/^## (.+)$/gm, "<h3>$1</h3>")
                .replace(/^# (.+)$/gm, "<h2>$1</h2>")
                .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
                .replace(/^- (.+)$/gm, "<li>$1</li>")
                .replace(/\n/g, "<br>");
            // Wrap consecutive <li> blocks in <ul>
            html = html.replace(/((?:<li>[^<]*<\/li><br>)+)/g, (match) => {
                return "<ul>" + match.replace(/<br>/g, "") + "</ul><br>";
            });
            return html;
        },
        async createWeeklyReport() {
            await this._createFixedReport('weekly_digest', "/api/reports/weekly-digest");
        },
        async createMonthlyReport() {
            await this._createFixedReport('deep_report', "/api/reports/deep-report");
        },
        async _createFixedReport(type, url) {
            if (!this.currentVehicleId) return;
            this.reportLoading = true;
            this.reportLoadingType = type;
            try {
                // 报告期独立（D15）：不传 rangeStart/rangeEnd，后端固定 7/30 天
                const data = await this.apiFetch(url, { method: "POST", json: { vehicle_id: this.currentVehicleId } });
                if (data) {
                    this.reportContent = data.content ? data.content : "生成失败，请稍后重试。";
                    await this.loadReports();
                }
            } finally {
                this.reportLoading = false;
                this.reportLoadingType = null;
            }
        },

        // --- Post detail ---
        openPostDetail(post) {
            this.postDetail = post;
            this.postDetailOpen = true;
        },

        // --- Collection ---
        phaseIcon(ph) {
            return {pending:'○', collecting:'◐', done:'✓', skipped:'⏭', error:'✕'}[ph] || '○';
        },
        showCollectPanel() {
            // 采集中 或 有 env_warning（社媒被跳过）时显示，让"伪 completed"无所遁形
            return ['collecting','analyzing','enriching','calculating'].includes(this.pipelinePhase)
                || !!(this.collectionProgress && this.collectionProgress.env_warning);
        },
        async triggerCollection() {
            if (this.fleetCollecting) { this.showToast("全车采集进行中，请等待完成后再点采集", "info"); return; }
            this.loading = true;
            this.pipelinePhase = "collecting";
            const data = await this.apiFetch(`/api/vehicles/${this.currentVehicleId}/collect`, { method: "POST" });
            if (!data) { this.loading = false; this.pipelinePhase = ""; return; }
            if (data.status === "already_running") {
                this.pipelinePhase = data.phase;
                // F-1：复用 refresh 的 D3 模式，查 /status 区分单车/全车 + toast（对齐 app.js:1289-1301）
                const st = await this.apiFetch("/api/fleet/status", { silent: true });
                if (st && st.in_progress_count >= 2) {
                    this.showToast(`全车采集进行中（${st.in_progress_count} 台），请等待完成`, "info");
                } else {
                    const label = {collecting:"采集中", analyzing:"分析中", calculating:"计算中", refreshing:"刷新中", "collecting(db_lock)":"采集中"}[data.phase] || data.phase;
                    this.showToast(`该车正在${label}，请等待完成`, "info");
                }
                // D2：不提前 return——继续轮询观察在跑任务，_pollPipeline 终态复位 loading + 重载数据
            }
            this._startPolling();
        },
        _startPolling() {
            if (this.pipelinePollTimer) clearInterval(this.pipelinePollTimer);
            this.pipelinePollTimer = setInterval(() => this._pollPipeline(), 3000);
            this._pollPipeline();
        },
        async _pollPipeline() {
            // 轮询用 silent：单个周期失败不应弹 toast 刷屏，保持继续轮询
            const [data, pd] = await Promise.all([
                this.apiFetch(`/api/vehicles/${this.currentVehicleId}/pipeline-status`, { silent: true }),
                this.apiFetch(`/api/vehicles/${this.currentVehicleId}/progress`, { silent: true }),
            ]);
            if (!data) return;  // 状态拉取失败 — 保持轮询
            this.pipelinePhase = data.phase;
            this.pipelineInfo = data;
            if (pd) {
                this.collectionProgress = pd;
                // P2-6：refreshing 时清空平台区（progress.platforms 为空 dict）
                if (pd.overall_phase === "refreshing" || this.refreshing) {
                    this.collectionProgress.platforms = {};
                }
            }

            if (data.phase === "completed" || data.phase === "error") {
                clearInterval(this.pipelinePollTimer);
                this.pipelinePollTimer = null;
                this.loading = false;
                // P2-2：区分 completed/error；refreshing 完成走 _onRefreshCompleted
                if (this.refreshing) {
                    if (data.phase === "completed") {
                        await this._onRefreshCompleted();
                    } else {
                        this.showToast("刷新失败：" + (data.error || "未知错误"), "error");
                        this.refreshing = false;
                    }
                } else if (data.phase === "completed") {
                    await this.onVehicleChange();
                } else {
                    this.showToast("采集失败", "error");
                }
            }
        },
        // --- 单车互动刷新（P0-3 异步 task + P1-2 DB 契约对齐）---
        async triggerRefreshEngagement() {
            if (!this.currentVehicleId) return;
            if (this.loading || this.fleetCollecting) { this.showToast("采集进行中，请等待完成后再刷新互动数", "info"); return; }
            this.refreshing = true;
            this.pipelinePhase = "refreshing";
            const data = await this.apiFetch(`/api/vehicles/${this.currentVehicleId}/refresh-engagement`, { method: "POST" });
            if (!data) { this.refreshing = false; this.pipelinePhase = ""; return; }
            if (data.status === "already_running") {
                // 复位预置的 "refreshing"（不覆盖成真实 phase——本分支提前 return 无轮询，
                // 真实 phase 会命中 showCollectPanel 致面板+状态点卡死）
                this.pipelinePhase = "";
                // D3：查 /status 区分单车/全车（单一真相源，P2-2）
                const st = await this.apiFetch("/api/fleet/status", { silent: true });
                if (st && st.in_progress_count >= 2) {
                    this.showToast(`全车采集进行中（${st.in_progress_count} 台），请等待完成后再刷新互动数`, "info");
                } else {
                    const label = {collecting:"采集中", analyzing:"分析中", calculating:"计算中", refreshing:"刷新中", "collecting(db_lock)":"采集中"}[data.phase] || data.phase;
                    this.showToast(`该车正在${label}，请等待完成后再刷新互动数`, "info");
                }
                this.refreshing = false;
                return;
            }
            this._startPolling();
        },
        // D2：跨会话恢复 fleetCollecting
        async _restoreFleetState() {
            const st = await this.apiFetch("/api/fleet/status", { silent: true });
            if (!st || !st.is_running || !st.vehicles.length) return;
            this.fleetCollecting = true;
            // P1-3：必须设 fleetStartTime，否则 _pollFleet 首轮 Date.now()-0 > 120min 判超时
            this.fleetStartTime = Date.now();
            this._startFleetPolling(st.vehicles.map(v => v.id));
        },
        async _onRefreshCompleted() {
            this.showToast("互动数 + 热度已更新", "success");
            await this._reloadAfterRefresh();
            this.refreshing = false;
        },
        async _reloadAfterRefresh() {
            // P1-5：分级重载，只重载互动数相关组件，跳过 defect 避免 LLM cache miss
            if (!this.currentVehicleId) return;
            await Promise.all([
                this.loadOverview(),
                this.loadTrend(),              // refresh 管线已重算 heat_metrics
                this.loadTopPosts(),
                this.loadNegativeRadar(),
                this.loadPosts(1),
                this.loadControversialPosts(),
                this.loadCollectionStatus(),    // P1-3：刷新后更新"上次采集"时间
            ]);
            this.renderAllCharts();
        },
        // --- 全车增量采集（P0-1 方法内关菜单 + P1-4 容错 + 120min 超时）---
        async triggerFleetCollect() {
            this.showOverflow = false;  // P0-1：方法内关菜单
            if (this.loading || this.refreshing) { this.showToast("单车任务进行中，请等待完成后再全车采集", "info"); return; }
            if (this.fleetCollecting) return;
            this.fleetCollecting = true;
            this.fleetStartTime = Date.now();  // P1-4：超时兜底
            const data = await this.apiFetch("/api/fleet/collect", { method: "POST" });
            if (!data) { this.fleetCollecting = false; return; }
            const msg = `已触发 ${data.started.length} 车采集，跳过 ${data.skipped.length} 车（频率分层）`;
            this.showToast(msg, "success");
            this.openFleet(true);
            if (data.started.length > 0) {
                this._startFleetPolling(data.started);
            } else {
                this.fleetCollecting = false;
            }
        },
        _startFleetPolling(vids) {
            this.fleetStartedVids = vids;
            if (this.fleetPollTimer) clearInterval(this.fleetPollTimer);
            this.fleetPollTimer = setInterval(() => this._pollFleet(), 5000);
            this._pollFleet();
        },
        async _pollFleet() {
            // P1-4：120min 超时兜底
            if (Date.now() - this.fleetStartTime > 120 * 60 * 1000) {
                clearInterval(this.fleetPollTimer);
                this.fleetPollTimer = null;
                this.fleetCollecting = false;
                this.showToast("全车采集超时（120min），已强制结束", "error");
                return;
            }
            const statuses = await Promise.all(
                this.fleetStartedVids.map(vid =>
                    this.apiFetch(`/api/vehicles/${vid}/pipeline-status`, { silent: true })
                )
            );
            // P1-4：null 视作"未完成继续轮询"（不因单轮 null 永久卡死）
            const anyNull = statuses.some(s => !s);
            if (anyNull) return;  // 继续轮询
            const allDone = statuses.every(s => s.phase === "completed" || s.phase === "error");
            if (allDone) {
                clearInterval(this.fleetPollTimer);
                this.fleetPollTimer = null;
                this.fleetCollecting = false;
                const failed = statuses.filter(s => s.phase === "error").length;
                const msg = `全车采集完成，${statuses.length - failed} 成功 / ${failed} 失败`;
                this.showToast(msg, failed > 0 ? "error" : "success");
                this.openFleet(true);
            }
        },

        // --- Search ---
        onSearchInput() {
            clearTimeout(this.searchDebounceTimer);
            const q = this.searchQuery.trim();
            if (!q) {
                this.searchResults = [];
                return;
            }
            this.searchDebounceTimer = setTimeout(async () => {
                // 联想搜索高频后台调用，失败静默（下拉不出现即为反馈）
                this.searchResults = await this.apiFetch(`/api/vehicles/search?q=${encodeURIComponent(q)}`, { silent: true }) || [];
            }, 300);
        },
        onSearchFocus() {},
        onSearchBlur() {
            setTimeout(() => { this.searchResults = []; }, 200);
        },
        selectVehicle(v) {
            this.currentVehicleId = v.id;
            this.searchQuery = `${v.name} (${v.brand})`;
            this.searchResults = [];
            this.onVehicleChange();
        },
        // --- 车队总览（D14） ---
        async openFleet(force = false) {
            this.showFleet = true;
            // §11.2：去掉缓存永不刷新，支持 force 刷新
            if (this.fleetOverview.length && !force) return;  // 已加载过，直接展示
            this.fleetLoading = true;
            try {
                // 相对路径：与 apiFetch 同口径，嵌入 Prism 时解析到 /sentiment-board/api/...
                const resp = await fetch("api/dashboard/fleet-overview");
                if (resp.ok) this.fleetOverview = await resp.json();
            } catch (e) { console.error("fleet-overview", e); }
            finally { this.fleetLoading = false; }
        },
        selectVehicleFromFleet(v) {
            this.showFleet = false;
            // 复用 selectVehicle：补 brand 兼容 fleet 项结构
            this.selectVehicle({ id: v.id, name: v.name, brand: v.brand || "" });
        },
        riskLevelLabelFor(level) {
            return { low: '低', medium: '中', high: '高', insufficient: '样本不足', none: '无' }[level] || '--';
        },
    },
}).mount("#app");
