# Design System Master File — ClassFee Manager（班费收支系统）

> **LOGIC:** 构建具体页面前，先检查 `design-system/pages/[page-name].md`。
> 若该文件存在，其规则**覆盖**本 Master 文件；否则严格遵循以下规则。

---

**Project:** ClassFee Manager
**Finalized:** 2026-09-25
**Category:** Financial Admin Dashboard（内部管理后台，非营销页）
**Source:** ui-ux-pro-max `--design-system`（Glassmorphism 方向）+ `--stack vue` + `--domain chart/ux`

**设计基调**：浅色玻璃拟态 + 石板灰文字 + 绿色为「收入/正向」语义色。
管理后台需白天长时间阅读，故采用 Light-first；深色仅作为可选主题。

---

## 1. Color Palette

### 1.1 语义 Token（组件中禁止写裸 hex，一律用变量）

| Role | Hex | CSS Variable | 用途 |
|------|-----|--------------|------|
| Primary | `#0F172A` | `--color-primary` | 主按钮、标题、侧边栏选中态 |
| On Primary | `#FFFFFF` | `--color-on-primary` | 主按钮文字 |
| Secondary | `#1E293B` | `--color-secondary` | 次级深色块 |
| Accent/CTA | `#22C55E` | `--color-accent` | 「记收入」CTA、缴费完成态 |
| On Accent | `#0F172A` | `--color-on-accent` | 绿底上的文字（对比度 ≈8:1） |
| Background | `#F5F7FB` | `--color-background` | 页面底色 |
| Foreground | `#0F172A` | `--color-foreground` | 正文 |
| Card | `rgba(255,255,255,0.72)` | `--color-card` | 玻璃卡片（需 `backdrop-filter`） |
| Card Foreground | `#0F172A` | `--color-card-foreground` | 卡片标题/数值 |
| Muted | `#EEF2F7` | `--color-muted` | 分隔、禁用底、表头底 |
| Muted Foreground | `#5A6779` | `--color-muted-foreground` | 次要文字（白底 5.7:1，玻璃卡/浅底 5.3:1 ✓） |
| Border | `rgba(15,23,42,0.08)` | `--color-border` | 1px 卡片描边 |
| Destructive | `#DC2626` | `--color-destructive` | 「记支出」、危险操作 |
| Destructive Text | `#B91C1C` | `--color-destructive-text` | 错误文案（白底 5.9:1 ✓） |
| Income Text | `#146C36` | `--color-income` | 收入金额文字（白底 6.5:1、绿底标签 5.7:1 ✓） |
| Expense Text | `#DC2626` | `--color-expense` | 支出金额文字 |
| Info | `#2563EB` | `--color-info` | 提示、链接 |
| Ring | `#2563EB` | `--color-ring` | 焦点环 `0 0 0 3px rgba(37,99,235,.35)` |

**色彩规则**
- 收入/支出**不得只靠红绿区分**：必须同时带 `+` / `−` 符号或「收入/支出」文字标签。
- 玻璃卡片背景必须配 `backdrop-filter: blur(16px)` + 1px 描边，否则透明度在复杂背景上不可读。

### 1.2 图表配色（来自 `--domain chart`）

| 序列 | 颜色 | 编码方式 |
|------|------|----------|
| 收入 | `#22C55E` | 实线 + 直接数值标签 |
| 支出 | `#EF4444` | 虚线（`borderDash: [6,4]`）+ 直接数值标签 |
| 余额 | `#2563EB` | 点划线 + 直接数值标签 |

- 趋势图：折线/面积图，填充不透明度 ≤20%，数据点 ≥4 个才画（<4 用统计卡）。
- 分类占比：**环形图，切片 ≤6**，>6 类合并为「其他」；每片直接标百分比，配可排序数据表兜底。
- 缴费完成率：进度条/华夫格（100 格），附百分比文字，不靠颜色单独表达。
- 永远提供图例 + Tooltip + 数据表（accessible fallback）。

---

## 2. Typography

- **数字/代码：** Fira Code（`font-variant-numeric: tabular-nums`，金额列必须等宽数字）
- **正文：** Fira Sans → **中文回退**：`"PingFang SC", "Microsoft YaHei", sans-serif`（Fira 无 CJK 字形）
- **Google Fonts:**
  ```css
  @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
  ```

| 层级 | 字号 | 字重 | 行高 |
|------|------|------|------|
| 页面标题 h1 | 24px | 600 | 1.3 |
| 区块标题 h2 | 18px | 600 | 1.4 |
| 正文 / 表格 | 14px | 400 | 1.5 |
| 辅助说明 | 12px | 400 | 1.5（**下限 12px**） |
| 大数字（余额） | 32–40px | 600 Fira Code | 1.2 |

---

## 3. Spacing / Shadow / Radius

| Token | Value | 用途 |
|-------|-------|------|
| `--space-xs` | 4px | 图标与文字 |
| `--space-sm` | 8px | 控件内间距（触控最小间距） |
| `--space-md` | 16px | 卡片内边距、栅格间距 |
| `--space-lg` | 24px | 区块间距 |
| `--space-xl` | 32px | 页面边距（≥1024px） |

| Shadow | Value | 用途 |
|--------|-------|------|
| `--shadow-sm` | `0 1px 2px rgba(15,23,42,.06)` | 静态卡片 |
| `--shadow-md` | `0 4px 12px rgba(15,23,42,.08)` | 卡片 hover |
| `--shadow-lg` | `0 12px 32px rgba(15,23,42,.12)` | 弹窗/下拉 |

**Radius：** 卡片/按钮 `8px`，弹窗 `16px`，标签 `999px`。

---

## 4. Component Specs

### 按钮
```css
.btn-primary { background:#0F172A; color:#fff; height:40px; padding:0 20px;
  border-radius:8px; font-weight:600; cursor:pointer; transition:all 200ms ease; }
.btn-primary:hover { background:#1E293B; box-shadow:var(--shadow-md); }
.btn-accent   { background:#22C55E; color:#0F172A; }   /* 记收入 */
.btn-danger   { background:#DC2626; color:#fff; }       /* 记支出/删除 */
.btn:focus-visible { outline:none; box-shadow:var(--ring); }
/* 最小高度 40px（触控 ≥44px 区域），移动端主操作 44px */
```

### 玻璃卡片
```css
.card {
  background: var(--color-card);
  backdrop-filter: blur(16px);
  border: 1px solid var(--color-border);
  border-radius: 12px; padding: var(--space-md);
  box-shadow: var(--shadow-sm);
  transition: box-shadow 200ms ease, transform 200ms ease;
}
.card:hover { box-shadow: var(--shadow-md); }
@media (prefers-reduced-motion: reduce) { * { transition-duration:.01ms !important; } }
```

### 表单（来自 `--domain ux`，High 优先级）
- **标签可见**，禁止仅用 placeholder 当标签；`label` 与 `input` 用 `for/id` 关联。
- **blur 时校验**，禁止仅在提交时报错。
- **错误就地显示**在字段下方，`aria-describedby` 关联，红边 + 文案同时给。
- 提交失败在表单**顶部**给 `role="alert"` 错误摘要并把焦点移过去（可键盘/读屏找到）。
- 错误必须给**恢复路径**（怎么改、按钮可重试）。
- 金额输入：`inputmode="decimal"`，`step="0.01"`，失焦格式化为 `¥1,234.56`，空值/负值/超限给具体文案。

### 表格
- 金额列右对齐 + `tabular-nums`；首列左对齐。
- 表头 `background: var(--color-muted)`，行 hover `rgba(15,23,42,.04)`。
- 移动端不横向滚动：转为卡片式列表（≤768px）。
- 空状态给出「去记一笔」的引导按钮，而不是空白。

### 弹窗
```css
.modal-overlay { background:rgba(15,23,42,.45); backdrop-filter:blur(4px); }
.modal { background:#fff; border-radius:16px; padding:24px; box-shadow:var(--shadow-lg);
  width:min(560px, 92vw); }
```
打开后焦点进入弹窗首个可输入项，`Esc` 关闭，关闭后焦点还给触发按钮。

---

## 5. Layout & Responsive

Mobile-first 断点：`768px`（平板）、`1024px`（桌面）。

- **≥1024px**：固定左侧导航 220px + 内容区，栅格统计卡 4 列。
- **768–1023px**：侧栏收起为图标，统计卡 2 列。
- **<768px**：侧栏变抽屉，底部固定「记一笔」主操作（44px 高），统计卡 1–2 列，表格转卡片列表。
- 断点一致，禁止写死 px 宽容器；`<meta name="viewport" content="width=device-width, initial-scale=1">`；不禁用缩放。
- 不出现横向滚动；固定顶栏需给内容区留 padding，内容不得被遮挡。

---

## 6. Motion

- 时长 150–300ms，缓动 `cubic-bezier(.4,0,.2,1)`；hover 只改 `opacity/box-shadow`，**不改布局尺寸**（避免 CLS）。
- 页面切换/列表进入可做 200ms 淡入 + 20ms stagger，上限 6 项。
- 数值变化可做滚动计数动画（余额），但必须尊重 `prefers-reduced-motion`（直接显示终值）。
- 加载态用骨架屏（预留高度，CLS < 0.1），按钮 loading 时禁用并显示 spinner。

---

## 7. Anti-Patterns（禁止）

- ❌ 用 emoji 当图标 → 用 Element Plus Icons / Lucide SVG
- ❌ 裸 hex 写在组件里 → 一律语义 token
- ❌ 只靠红绿区分收支 → 必须配 +/− 符号或文字
- ❌ placeholder 代替 label；错误只在提交后、只在顶部出现
- ❌ 点击元素缺 `cursor:pointer`；点击区域 < 40px
- ❌ 移动端横向滚动、禁用缩放
- ❌ 移除 focus ring、0ms 状态切换、无视 reduced-motion
- ❌ 图片不给宽高导致布局抖动（CLS）

---

## 8. Pre-Delivery Checklist

- [ ] 无 emoji 图标，图标来自同一 SVG 图标集
- [ ] 所有可点击元素 `cursor:pointer`，触控目标 ≥40px、间距 ≥8px
- [ ] hover 过渡 150–300ms，且不引发布局位移
- [ ] 正文对比度 ≥4.5:1（含灰字、绿/红金额）
- [ ] 键盘可达：焦点环可见、弹窗焦点管理、Esc 关闭
- [ ] 表单 blur 校验 + 就地错误 + `role="alert"` 错误摘要
- [ ] `prefers-reduced-motion` 被尊重
- [ ] 响应式 375 / 768 / 1024 / 1440 无横向滚动
- [ ] 图表有图例、Tooltip、数据表兜底
- [ ] 骨架屏/加载态预留空间，CLS < 0.1
