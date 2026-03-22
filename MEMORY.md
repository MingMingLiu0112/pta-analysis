# MEMORY.md - CodeMan 长期记忆

## 关于用户

- **GitHub**: MingMingLiu0112
- **主要需求**: 股票分析自动化
- **偏好**: 使用 GitHub Actions 运行股票分析，推送到飞书

## 项目

### 1. 股票分析项目 (daily_stock_analysis)
- **仓库**: https://github.com/MingMingLiu0112/daily_stock_analysis
- **来源**: 从 ZhuLinsen/daily_stock_analysis fork
- **持仓股票**: 603993（洛阳钼业）、600183（生益科技）、601899（紫金矿业）
- **运行方式**: GitHub Actions

## 技术配置

- **AI 模型**: MiniMax-M2.5-highspeed
- **API**: OpenAI 兼容模式 (api.minimaxi.com)
- **推送**: 飞书机器人 Webhook

## GitHub 配置

- **用户名**: MingMingLiu0112
- **Token**: `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`（已配置到 futures-options-analysis）
- **期货项目**: https://github.com/MingMingLiu0112/futures-options-analysis
- **飞书 Secret**: 已配置到仓库 Secrets

## 项目记录

- 2026-03-22: 创建期货期权分析项目 futures-options-analysis
  - 仓库: https://github.com/MingMingLiu0112/futures-options-analysis
  - 包含 IV Rank/Skew/基差共振等信号计算
  - GitHub Actions 定时运行（08:00/15:00/21:00 北京时间）

## 已知问题

- 2026-03-18: 会话曾被重置，记忆丢失 → 已建立 memory/ 目录自动保存
