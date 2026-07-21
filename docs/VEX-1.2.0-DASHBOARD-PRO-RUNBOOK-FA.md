# راهنمای داشبورد حرفه‌ای VEX 1.2.0

## هدف نسخه

نسخه 1.2.0 داشبورد را به یک ورک‌استیشن سبک، قابل تنظیم و مناسب Replay کندل‌به‌کندل تبدیل می‌کند. موتور بک‌تست، بروکر و Strategy Runtime تغییر ماهوی نکرده‌اند؛ تمرکز این نسخه روی مسیر WebSocket تا Chart، کنترل حافظه مرورگر و تجربه کاربری است.

## نصب تمیز

پیشنهاد می‌شود ZIP کامل را در پوشه‌ای جدید Extract کنی:

```text
G:\PythonProject\vex-1.2.0
```

در PowerShell:

```powershell
cd G:\PythonProject\vex-1.2.0
$env:UV_LINK_MODE = "copy"
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```

## اجرای Docker

ابتدا نسخه قدیمی را متوقف کن:

```powershell
docker compose -f .\compose.yaml down --remove-orphans
Remove-Item .\compose.override.yaml -ErrorAction SilentlyContinue
```

سپس:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 -ForceRebuild
```

آدرس‌ها:

```text
Dashboard  http://127.0.0.1:8000
Engine     http://127.0.0.1:8001
```

بعد از اولین اجرا یک بار `Ctrl + F5` بزن تا Asset قدیمی مرورگر استفاده نشود.

## اجرای محلی جداگانه

PowerShell اول:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\start-engine.ps1
```

PowerShell دوم:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard-only.ps1
```

## پروفایل‌های Render

در Top Bar سه حالت وجود دارد:

- `Smooth`: برای Replay بصری آهسته و حرکت نرم.
- `Balanced`: حالت پیش‌فرض.
- `Throughput`: برای سرعت‌های بالا و ادغام Frameهای بیشتر.

برای مشاهده یک Strategy به‌شکل TradingView Replay از `Smooth` یا `Balanced` استفاده کن. برای تمام‌کردن سریع Run از `Throughput` استفاده کن.

## Timeframeها

Chart Selector همیشه این موارد را دارد:

```text
1m | 5m | 15m | 1H | 4H | 1D
```

Timeframeهایی که در Run اشتراک ندارند غیرفعال می‌شوند. تعویض Timeframe باعث نمایش Candle آینده نمی‌شود؛ فقط Candleهای بسته‌شده تا Cursor فعلی نمایش داده می‌شوند.

## قفل Scale

### تعداد Candle ثابت

در کنترل Chart یکی از این Presetها را انتخاب کن:

```text
60 | 100 | 160 | 240 | 400 | 800
```

`Follow` و `X Lock` را روشن نگه دار. در طول Replay تعداد Candleهای قابل مشاهده ثابت می‌ماند و Chart همراه Candle جدید جلو می‌رود.

### Scale دستی محور زمان

1. `X Lock` را خاموش کن.
2. Zoom و Pan دلخواه را انجام بده.
3. دکمه Capture کنار X را بزن.
4. `X Lock` را روشن کن.

### محدوده ثابت قیمت

1. `Y Lock` را خاموش کن.
2. محور قیمت را به محدوده دلخواه تنظیم کن.
3. Capture Y را بزن.
4. `Y Lock` را روشن کن.

تنظیمات برای هر `Symbol + Timeframe` جدا ذخیره می‌شوند.

## Focus و Layout

Presetهای Top Bar:

- `Focus`: فقط فضای اصلی Chart و کنترل Replay.
- `Balanced`: Chart همراه Inspector و Dock متعادل.
- `Analysis`: فضای بیشتر برای جداول و Analytics.

لبه Inspector و Bottom Dock قابل Drag است. اندازه‌ها در مرورگر ذخیره می‌شوند.

کلیدهای میانبر:

```text
Space       Play / Pause
Left        یک کندل عقب
Right       یک کندل جلو
R           Reset
F           Focus Chart
I           Inspector
D           Bottom Dock
M           Metrics
1..6        M1, M5, M15, H1, H4, D1
```

## Diagnostics

Diagnostics را فقط برای بررسی Performance روشن کن. HUD این اطلاعات را نشان می‌دهد:

- نرخ Render Chart
- تعداد Candleهای Browser Window
- تعداد نقاط Indicator
- اندازه آخرین WebSocket Batch
- تعداد Frameهای ادغام‌شده

برای بهترین Performance در استفاده روزمره Diagnostics را خاموش نگه دار.

## Strategy Drawing

Strategy همچنان از Chart Protocol استفاده می‌کند. Indicatorها و Drawingها به‌صورت Incremental اضافه می‌شوند و از State بروکر مستقل‌اند. دکمه `Studies` می‌تواند همه لایه‌های Strategy را موقتاً مخفی کند بدون اینکه Backtest متوقف شود.

## تست نسخه

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\quality.ps1
```

تست Docker و WebSocket:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-smoke.ps1
```

## نکته مرورگر

برای بهترین نتیجه از نسخه جدید Chrome یا Edge استفاده کن. بازبودن DevTools، Recording در Performance tab، افزونه‌های سنگین و تب‌های متعدد می‌تواند نرخ Render را کاهش دهد.
