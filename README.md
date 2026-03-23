# 09911.HK 量化信号监控系统

针对港股 **赤子城科技 (09911.HK)** 的自动化技术面信号监控工具。当特定技术条件被触发时生成 alert，辅助交易决策。

> 设计哲学：针对港股小盘股特性（流动性有限、资金驱动型、波动大）优化信号逻辑，避免大盘股指标的滞后性问题。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env  # 配置通知渠道（可选）

# 运行信号扫描
python main.py

# JSON 输出（供下游 AI agent 消费）
python main.py --json

# 仅计算，不发通知
python main.py --dry-run
```

**定时任务**（每日港股收盘后运行）：
```cron
30 16 * * 1-5 cd /path/to/newborntown_monitor && python main.py
```

## 信号体系

### 单一信号

| ID | 名称 | 级别 | 说明 |
|----|------|------|------|
| **A1** | 放量预警 | ⚠️ WATCH | 日成交量 > 2x 20日均量 |
| **A2** | 天量警报 | 🔴 ALERT | 日成交量 > 3x 20日均量，自动判断多空含义 |
| **A3** | 缩量信号 | 📊 INFO | 下跌趋势中连续2天量 < 60% 均量（正面信号） |
| **B1** | RSI超卖 | ⚠️ WATCH | RSI(14) < 30 |
| **B2** | RSI极端超卖 | 🔴 ALERT | RSI(14) < 20 |
| **B3** | RSI脱离超卖 | 📊 INFO | RSI从 <30 回升至 >30 |
| **B4** | RSI顶背离 | 🔴 ALERT | 价格创新高但RSI未创新高 |
| **B5** | RSI底背离 | 🔴 ALERT | 价格创新低但RSI未创新低 |
| **C1** | 支撑位测试 | ⚠️ WATCH | 价格触及关键支撑位 ±1% |
| **C2** | 支撑位跌破 | 🔴 ALERT | 收盘跌破支撑位 2%+ |
| **C3** | 阻力位突破 | 🔴 ALERT | 收盘突破阻力位 2%+ |
| **C4** | 200日均线交叉 | 🔴 ALERT | 价格上穿/下穿 200 日均线 |
| **D1** | 跌破布林下轨 | ⚠️ WATCH | 收盘 < BB 下轨 (20d, 2σ) |
| **D2** | 布林带收窄 | 📊 INFO | 带宽 < 均值 50%，大行情前兆 |
| **D3** | 回归布林通道 | 📊 INFO | 从下轨外回归通道内 |

### 复合信号（交易决策级别）

| ID | 名称 | 方向 | 条件 |
|----|------|------|------|
| **COMPOSITE-BUY-1** | 卖压衰竭+超卖反弹 | 🟢 买入 | RSI超卖回升 + 连续缩量 + 支撑位附近 + 布林通道内 |
| **COMPOSITE-BUY-2** | 趋势反转确认 | 🟢 买入 | RSI底背离 + 站上20d MA + 放量 + MACD转正 |
| **COMPOSITE-SELL-1** | 破位加速 | 🔴 卖出 | 跌破支撑 + 放量 + RSI走弱 + 布林下轨外 |
| **COMPOSITE-SELL-2** | 顶背离+出货 | 🔴 卖出 | RSI顶背离 + 天量收阴 + 阻力位压制 |

## 项目结构

```
main.py                    — 入口（CLI: --dry-run / --json / --verbose）
src/
  config.py                — 静态参数与阈值配置
  data_fetcher.py          — Yahoo Finance 数据拉取
  indicators.py            — 技术指标计算 (RSI, MACD, SMA, BB)
  signals.py               — 单一信号检测 (A1-D3)
  composite_signals.py     — 复合信号检测 (BUY-1/2, SELL-1/2)
  notifier.py              — Alert 格式化 + 分发
data/
  signals.db               — SQLite 历史信号存储（自动创建）
```

## 通知渠道

编辑 `.env` 配置（均为可选）：

| 渠道 | 环境变量 |
|------|----------|
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Slack** | `SLACK_WEBHOOK_URL` |
| **Email** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TO` |

未配置任何渠道时，alert 仍会输出到控制台并存入 SQLite。

## 关键价格水平

在 `src/config.py` 中维护，需定期手动更新：

| 参数 | 当前值 | 更新频率 |
|------|--------|----------|
| KEY_SUPPORT_1 | HKD 7.41 | 每次突破后重新评估 |
| KEY_SUPPORT_2 | HKD 6.15 | 季度 review |
| KEY_RESISTANCE_1 | HKD 8.05-8.18 | 每次突破后重新评估 |
| KEY_RESISTANCE_2 | HKD 9.20 | 每次突破后重新评估 |
| KEY_RESISTANCE_3 | ≈200d MA | 自动计算 |

## JSON 输出示例

```json
{
  "timestamp": "2026-03-23T16:00:00+08:00",
  "ticker": "09911.HK",
  "signal_id": "A2",
  "signal_name": "天量警报",
  "level": "ALERT",
  "message": "[09911.HK] 天量警报: 11.29M = 2.0x 均量。价格下跌。疑似 大规模出货/恐慌抛售。",
  "context": {
    "close": 7.82,
    "volume": 11290000,
    "volume_ratio": 2.04,
    "rsi_14": 28.5,
    "sma_20": 9.72,
    "sma_200": 10.88,
    "bb_lower": 7.95,
    "bb_upper": 11.49,
    "macd_histogram": -0.35,
    "nearest_support": 7.41,
    "nearest_resistance": 8.18
  },
  "composite_signals_active": ["COMPOSITE-SELL-1"]
}
```
