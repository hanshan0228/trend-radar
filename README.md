# 全渠道新产品趋势雷达 (Multi-Channel Trend Radar)

> 基于 qiayue 开源灵感改造的**全渠道、100% 免费、零付费 API Key 依赖**的新产品/新词捕获雷达。

---

## 🌟 核心特性与改造亮点

1. **彻底摆脱付费 API（0 成本运行）**：
   - 原项目依赖 AISA Twitter Autopilot (收费) 与 query.domains (收费)；
   - 本项目通过 **Google News 穿透语法 + 官方免 Key 接口 + ICANN 公开 RDAP 协议**，实现 **100% 零付费 API Key、零封号风险**！
2. **多渠道无缝融合 (Multi-Channel)**：
   - 🐦 **Twitter / X**：免 API 实时抓取过去 3 天带链接的 `just launched` / `introducing` 推文；
   - 🟠 **Show HN (Hacker News)**：官方免 Key 接口直连全球极客发布的首发新项目；
   - 🔴 **Reddit (r/SideProject)**：监控全网独立开发者的最新自荐作品；
   - 🟡 **Product Hunt**：追踪当日发布的新工具。
3. **域名法医与智能标绿 (≤ 30 天超新米)**：
   - 自动识别 `*.vercel.app`、`*.lovable.app` 等新一代 PaaS 部署子域；
   - 自动通过 RDAP 协议反查独立域名创建时间，对 **≤ 30 天** 的新鲜婴儿期项目**高亮绿框预警**！
4. **一键反查联动**：
   - 每张卡片自带一键跳转：`📈 Google Trends`、`🔎 Google 收录`、`💬 原始讨论帖`。

---

## 🚀 启动与使用

### 1. 运行服务（纯 Python 3 标准库，无需 pip install 任何依赖）：
```bash
python server.py
```

### 2. 访问控制台：
在浏览器中打开：
```
http://127.0.0.1:8989
```

### 3. 操作模式：
- **单次扫描**：选择你要监控的渠道，点击「全网扫描」；
- **自动巡逻**：开启「自动巡逻」，系统每 60 秒自动更新一次全网新出现的项目；
- **年限筛选**：下拉菜单选择「仅显示 ≤ 30 天超新米」，瞬间过滤掉老站。
