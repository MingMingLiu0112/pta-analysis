# MEMORY.md - CodeMan 长期记忆

## 关于用户

- **GitHub**: MingMingLiu0112
- **主要需求**: 股票/期货分析自动化
- **偏好**: 使用 GitHub Actions 运行分析，推送到飞书

## 项目

### 1. 期货技术分析 (futures-options-analysis)
- **仓库**: https://github.com/MingMingLiu0112/futures-options-analysis
- **定时**: 北京时间 08:00/15:00/21:00
- **分析品种**（2026-04-03更新）:
  - 橡胶2609、棕榈油2609、豆油2609、锰硅2605、燃油2605、聚丙烯2605
  - 焦煤2609、铁矿2609、苹果2610、不锈钢2605、棉花2609、生猪2605、纸浆2609、纯碱2609

### 2. 股票分析项目 (daily_stock_analysis)
- **仓库**: https://github.com/MingMingLiu0112/daily_stock_analysis
- **持仓**: 603993（洛阳钼业）、600183（生益科技）、601899（紫金矿业）

## 技术配置

- **AI 模型**: MiniMax-M2.5-highspeed
- **API**: OpenAI 兼容模式 (api.minimaxi.com)
- **飞书机器人**:
  - Webhook: `https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256`
  - App ID: `cli_a93a74737d7a5cc0`
  - App Secret: `ITgEfB7XN07z69JfadO06dfcPfZ5ylw6`

## ⚠️ 重要：GitHub Actions 限制
- 免费账户每月只有 **2000 分钟**运行时间
- **不要频繁触发 workflow** - 每2小时只做本地自查和群里汇报
- 仅在代码修好需要测试时，才触发一次 GHA

## GitHub 配置

- **Token**: （见 .env.github）
- **Workflow IDs**:
  - Futures Technical Analysis: 249723968
  - K-Line Chart Generator: 255265193（仅定时触发，无workflow_dispatch）

## 项目记录

- 2026-03-22: 创建期货期权分析项目
- 2026-04-03: 品种配置大更新，更换为橡胶/棕榈油/豆油/锰硅/燃油/聚丙烯/焦煤/铁矿/苹果/不锈钢/棉花/生猪/纸浆/纯碱

## 已知问题

- 2026-04-03: 新浪实时行情API编码问题 → 已修复（GBK）
- MACD信号未生效
- K线图仅在定时workflow触发时生成

## PTA分析项目 (pta-analysis)

- **仓库**: https://github.com/MingMingLiu0112/pta-analysis
- **策略**: 每2小时自查进度并群里汇报，不频繁触发GHA
- **当前版本**: v1.1
- **交易逻辑框架**（已沉淀到skills/futures-trading）:
  - 三维度：宏观基本面 + 技术面(缠论) + 期权印证
  - 动态权重：平静期技术=期权、驱动期弱化期权、杀期权阶段期权墙主导
  - 三级别：1分钟→5分钟→30分钟，操作级5分钟
  - **当前阶段**：资金规模有限，只关注**当月到期期权链**，暂不关注期限结构
  - **新增任务**：PTA生产成本计算（布伦特油→PX→PTA成本）+ 布伦特油日度监测

### 今日新增进展（2026-04-04）

- Python升级3.11.9 + akshare安装成功
- CTP接口 `option_contract_info_ctp()` 可用，484条PTA期权合约
- PX现货价接口 `futures_spot_price` 可用
- PTA生产成本计算：当前PX=9700 → PTA成本≈6653~7153元/吨
- 交易策略框架已完整沉淀到 futures-trading skill
- 布伦特原油接口 `futures_global_spot_em()` 可用
- 收到并整理刘明铭团队PTA期权逻辑文档（docs/PTA期货期权逻辑_原文.md）
- **期权核心框架**：价格+持仓+PCR三维组合、隐波曲面左右偏判断、四维共振与背离、恐慌底vs狂热顶非对称性、三大交易规则（规则A/B/C）、OEI情绪指数、动态仓位管理、实战经验阈值
- **待解决**:
  1. PTA期权链接口（AKShare CZCE期权不稳定，优先试 option_current_em）
  2. 杀期权阶段识别（期权墙梯度性持仓识别）
  3. 宏观平静/驱动状态自动判断

### 今日新增进展（2026-04-04）

- Python升级3.11.9 + akshare安装成功
- CTP接口 `option_contract_info_ctp()` 可用，484条PTA期权合约
- PX现货价接口 `futures_spot_price` 可用
- PTA生产成本计算：当前PX=9700 → PTA成本≈6653~7153元/吨
- 交易策略框架已完整沉淀到 futures-trading skill
- **Cron**: `/home/admin/.openclaw/workspace/codeman/pta_analysis/report_progress.sh`

## Skills 技能库

### futures-trading
期货技术分析技能，已沉淀在 `~/.openclaw/skills/futures-trading/`
- SKILL.md: 核心框架、指标体系、打分逻辑
- references/: 指标公式、期权IV、数据接口文档
