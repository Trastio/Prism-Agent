# 提示词回归门禁（prompt-gate）· 提案+验证（微 change · 主会话直修，2026-10-16）

> 用户拍板开工（制度基建四件裁剪：仅此一件必修；日巡检不做、同构映射随 L1-2、门槛自动判定挂上云）
> 依据：教材 7.10.4（系统提示应有与代码同等的版本控制与回归测试——渲染确定性/版本化快照/变更跑回归）；红线#5 护栏在执行层

## 机制

```
提示词层文件集（7件：AGENTS.md / SYSTEM.md / skills 4 md / verifier-prefix.ts）
   → sha256 指纹快照（eval/prompt_gate.json 台账，history 留痕）
   → .githooks/pre-commit（git config core.hooksPath 已装）：check 秒级比对
        绿=放行 / 变更未冒烟=拦（红条+冒烟指引）/ 从未=拦（首跑指引）
        显式绕过：PRISM_PROMPT_GATE_BYPASS=1（打印 BYPASSED 留痕后放行）
   → 冒烟 = prism.py eval start && node eval/runner.mjs --only=trap（一票否决线）
        && node eval/prompt_gate.mjs mark-green
   → runner.mjs 报告新增 prompt_files_hash（每份批跑报告自动绑定当时提示词版本）
```

设计取舍：pre-commit 只做秒级指纹比对（真跑冒烟 15-30 分钟不可挂 hook）；拦截+显式 bypass 而非静默警告——"改了提示词没跑回归"无法静默发生，绕过必须是显式动作。

## 范围拍板

- 不含 .pi/extensions/**（代码层，自有单测）；新增 skill 时须同步 PROMPT_FILES 清单（D1 三表互检同源教训已注码内）
- 冒烟=trap 10 题（提示词变更的主要风险面=红线行为）；frozen 基线立稳后可加抽样判分题

## 验证（全部主会话实跑）

| 项 | 结果 |
|---|---|
| 单测 | **20/20 绿**（含新增 4 例：文件集存在性/指纹稳定与变更/状态机三态/markGreen 留痕；修一个 CLI 入口守卫 bug——import 即执行 CLI） |
| CLI 三态 | never=2 → mark-green → green=0 实跑正确 |
| **hook 三场景** | 红态（改 AGENTS.md→exit 1+列文件+指引）/ bypass（=0+BYPASSED 留痕）/ 恢复绿（=0） |
| 安装 | git config core.hooksPath=.githooks ✓ + chmod +x |
| 首绿标记 | hash=4d52acba0126 / git=9e742e0；note 注明"以 v1.1 基线绿态起步（当前提示词即跑出 4.63/90% 那版），trap 冒烟绑定下轮批跑" |

## 遗留（如实）

- 首绿基于"当前提示词=v1.1 已验证行为"的等价判断，未跑独立 trap 冒烟（避免为标绿先花 1.5M tokens；下一次批跑自然覆盖）
- Windows 下 git hooks 走 git-bash sh，实测链路通；若 hooksPath 被全局配置覆盖需重设（一行命令，已写 hook 头注）
- runner 的 prompt_files_hash 已入报告字段（dry-run 不落盘，下轮批跑首见真值）
