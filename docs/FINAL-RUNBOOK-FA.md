# راهنمای نهایی اجرای VEX

## معماری سرویس‌ها

```text
Backtest Engine  http://127.0.0.1:8001
Dashboard        http://127.0.0.1:8000
Strategies       strategies/<package_id>/
Live work        data/live-runs/<run_id>/
Final replay     data/replay/runs/<run_id>/
```

موتور و داشبورد دو Process مستقل‌اند. اجرای Backtest متعلق به موتور است؛ بنابراین Restart کردن داشبورد اجرای فعال را متوقف نمی‌کند. Restart کردن خود موتور، Run فعال را متوقف می‌کند. Runهای تکمیل‌شده به‌صورت Replay Bundle پایدار باقی می‌مانند.

## نصب محلی روی Windows

```powershell
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```

## اجرای جداگانه موتور و داشبورد

PowerShell شماره ۱:

```powershell
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\start-engine.ps1
```

تست موتور:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
powershell -ExecutionPolicy ByPass -File .\scripts\engine-smoke.ps1
```

PowerShell شماره ۲:

```powershell
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard-only.ps1
```

Dashboard:

```text
http://127.0.0.1:8000
```

## اجرای جداگانه با Docker

ساخت Cache و اجرای فقط موتور:

```powershell
docker compose up -d --build bootstrap engine
```

اجرای داشبورد در زمان دلخواه:

```powershell
docker compose up -d dashboard
```

توقف یا Restart فقط داشبورد:

```powershell
docker compose stop dashboard
docker compose up -d --force-recreate dashboard
```

بررسی کامل HTTP و WebSocket:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-smoke.ps1
```

## ساخت Strategy مستقل

Template را Copy کن:

```powershell
Copy-Item .\strategies\_template .\strategies\my_strategy -Recurse
```

ساختار لازم:

```text
strategies/my_strategy/
├── __init__.py
├── package.yaml
├── strategy.py
├── strategy.yaml
├── run.yaml
├── runtime.yaml
└── README.md
```

در `package.yaml` مقدارها را اصلاح و در پایان فعال کن:

```yaml
schema_version: 1.0.0
package_id: my_strategy
descriptor_path: strategy.yaml
run_config_path: run.yaml
runtime_config_path: runtime.yaml
symbol_profile_paths:
  - ../../examples/configs/symbol_xauusd.yaml
import_report_path: ../../data/cache/xauusd_mt5_2025_2026/2/import-report.json
enabled: true
```

در `strategy.yaml` Entrypoint باید با نام پوشه و کلاس یکسان باشد:

```yaml
schema_version: 1.0.0
strategy_id: my_strategy
name: My Strategy
version: 1.0.0
entrypoint: my_strategy.strategy:MyStrategy
```

پس از ذخیره فایل‌ها، بدون Restart موتور Catalog را Refresh کن:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\strategy-refresh.ps1
```

## شروع Backtest Candle-by-Candle

Run به‌صورت Pause ساخته می‌شود:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId my_strategy `
  -RunId run_my_strategy_v1 `
  -MaxCloseBatches 5000
```

یک قدم دقیق:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_my_strategy_v1 `
  -Action step_forward `
  -Value 1
```

Play، Pause و سرعت:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 -RunId run_my_strategy_v1 -Action play
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 -RunId run_my_strategy_v1 -Action pause
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 -RunId run_my_strategy_v1 -Action set_speed -Value 50
```

بازسازی یک کندل عقب‌تر و Reset:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 -RunId run_my_strategy_v1 -Action step_backward
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 -RunId run_my_strategy_v1 -Action reset
```

Parameter Override بدون تغییر فایل Strategy:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId my_strategy `
  -RunId run_my_strategy_params_v1 `
  -ParametersJson '{"lookback":50,"risk_percent":"0.5"}'
```

## ترتیب دقیق هر Step

هر `step_forward` دقیقاً یک Synchronized Close Batch را اجرا می‌کند:

1. Data Engine کندل‌های بسته‌شده در Timestamp جاری را تحویل می‌دهد.
2. Broker کندل Execution Timeframe را پردازش می‌کند.
3. Pending Order، SL و TP بررسی می‌شوند.
4. Fill، Position، PnL، Margin و Account به‌روزرسانی می‌شوند.
5. Broker Eventها به Strategy می‌رسند.
6. Strategy کندل‌های بسته‌شده Subscriptionها را دریافت می‌کند.
7. Strategy می‌تواند Order، مدیریت Position، Indicator، Drawing و Log تولید کند.
8. Actionها توسط Broker اجرا می‌شوند.
9. Feedback مربوط به Order و Position دوباره به Strategy می‌رسد.
10. یک Replay Frame منتشر می‌شود.
11. موتور تا Step یا Tick بعدی Play صبر می‌کند.

در حالت M1، هر Step یک M1 تازه‌بسته‌شده را جلو می‌برد و هر M5، M15، H1، H4 یا D1 که همان لحظه بسته شده باشد نیز در همان Batch تحویل می‌شود.

## APIهای Strategy

```python
context.market.history(...)
context.market.latest(...)
context.market.forming(...)
context.portfolio.open_positions()
context.orders.market(...)
context.orders.limit(...)
context.orders.stop(...)
context.orders.close_position(...)
context.orders.modify_position_protection(...)
context.chart.declare_pane(...)
context.chart.declare_series(...)
context.chart.plot_scalar(...)
context.chart.marker(...)
context.chart.rectangle(...)
context.chart.risk_reward(...)
context.log.info(...)
```

Strategy نباید CSV یا Parquet را مستقیم بخواند و نباید Broker State را مستقیم تغییر دهد.

## Source Snapshot و تعویض Strategy

در لحظه ساخت Run، کل Package انتخاب‌شده در این مسیر Snapshot می‌شود:

```text
data/live-runs/<run_id>/strategy-source/<package_id>/
```

Rewind و Finalization از همین Snapshot استفاده می‌کنند. بنابراین می‌توان Package اصلی را تغییر داد و Catalog را Refresh کرد؛ Runهای قبلی با نسخه قبلی ادامه می‌دهند و Runهای جدید نسخه جدید را می‌گیرند.

پس از اتمام، Snapshot در Replay Bundle ذخیره می‌شود:

```text
data/replay/runs/<run_id>/strategy-source/<package_id>/
```

Manifest دارای Path و SHA-256 مربوط به Source است.

## Strategy تست موجود

Package آماده:

```text
strategies/sma_cross_demo
```

اجرای آن:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId sma_cross_demo `
  -RunId run_sma_manual_v1 `
  -MaxCloseBatches 5000
```

این Strategy دو SMA را رسم می‌کند، Marker سیگنال و Risk/Reward Drawing می‌سازد، Long و Short باز می‌کند، SL/TP دارد و Position مخالف را مدیریت می‌کند. هدف آن تست Integration است، نه ادعای سوددهی.

## تست نهایی پروژه

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\quality.ps1
powershell -ExecutionPolicy ByPass -File .\scripts\full-debug.ps1
```

خروجی Run تکمیل‌شده:

```text
data/replay/runs/<run_id>/replay.sqlite3
data/replay/runs/<run_id>/analytics-report.json
data/replay/runs/<run_id>/strategy-report.json
data/replay/runs/<run_id>/manifest.json
```

## تست مستقل ارتباط موتور و داشبورد

این تست دو سرویس را روی پورت‌های موقت و مستقل بالا می‌آورد، REST و WebSocket را بررسی می‌کند، یک Run زنده می‌سازد، یک کندل جلو می‌رود و Finalization و Analytics را تأیید می‌کند:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\separated-services-smoke.ps1
```

گزارش آن در مسیر زیر ذخیره می‌شود:

```text
data\replay\final-separated-services-smoke-report.json
```
