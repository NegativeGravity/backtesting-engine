# راهنمای نصب و اجرای VEX 1.1.0

این نسخه روی اجرای روان Replay، بزرگ‌شدن فضای Chart، جلوگیری از ناپدیدشدن Candleها و قفل‌کردن Scale تمرکز دارد.

## نصب تمیز پیشنهادی

نسخه جدید را در یک پوشه تازه Extract کن:

```text
G:\PythonProject\vex-1.1.0
```

سپس:

```powershell
cd G:\PythonProject\vex-1.1.0
$env:UV_LINK_MODE = "copy"
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```

## توقف نسخه قبلی

```powershell
cd G:\PythonProject\backtesting-engine
docker compose -f .\compose.yaml down --remove-orphans
```

در پنجره‌های اجرای Local نیز `Ctrl+C` بزن. برای بستن Processهای باقی‌مانده روی پورت‌های پروژه:

```powershell
$Ports = 8000, 8001, 18000, 18001
foreach ($Port in $Ports) {
    Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}
```

اگر Hotfix قدیمی ساخته شده، فایل زیر را حذف یا Rename کن:

```powershell
Remove-Item .\compose.override.yaml -ErrorAction SilentlyContinue
```

## اجرای Docker

```powershell
cd G:\PythonProject\vex-1.1.0
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 -ForceRebuild
```

وضعیت:

```powershell
docker compose ps
```

Dashboard:

```text
http://127.0.0.1:8000
```

Engine:

```text
http://127.0.0.1:8001/api/health
```

## اجرای Local و جداگانه

PowerShell اول:

```powershell
cd G:\PythonProject\vex-1.1.0
powershell -ExecutionPolicy ByPass -File .\scripts\start-engine.ps1 -Port 18001
```

PowerShell دوم:

```powershell
cd G:\PythonProject\vex-1.1.0
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard-only.ps1 `
  -Port 18000 `
  -EnginePort 18001
```

Dashboard:

```text
http://127.0.0.1:18000
```

## Timeframeهای Chart

Chart همیشه این دکمه‌ها را نشان می‌دهد:

```text
1m | 5m | 15m | 1H | 4H | 1D
```

معادل:

```text
M1 | M5 | M15 | H1 | H4 | D1
```

## تنظیم Horizontal Scale

دو روش وجود دارد:

### روش عددی

از منوی `Candles` تعداد Candle قابل مشاهده را انتخاب کن:

```text
60, 100, 160, 240, 400, 800
```

`Follow` و `X Scale` را فعال نگه دار. Chart با همان تعداد Candle به سمت جلو حرکت می‌کند.

### روش دستی و دقیق

1. `X Scale` را خاموش کن.
2. با Mouse Wheel یا Drag روی محور زمان Zoom را دقیق تنظیم کن.
3. دوباره `X Scale` را فعال کن.
4. موتور تعداد Candle و Right Offset فعلی را ثبت می‌کند.
5. در صورت تنظیم دوباره، دکمه Save کنار X Scale را بزن.

این تنظیم برای Symbol و Timeframe فعلی در مرورگر ذخیره می‌شود و در کل Backtest ثابت می‌ماند.

## تنظیم Vertical Price Scale

1. محور قیمت سمت راست را Drag کن تا محدوده دلخواه ساخته شود.
2. `Y Scale` را فعال کن.
3. محدوده قیمت فعلی قفل می‌شود.
4. برای ذخیره محدوده جدید، دکمه Save کنار Y Scale را بزن.
5. برای برگشت به Auto Scale، `Y Scale` را خاموش کن.

## حالت Chart Focus

دکمه Maximize داخل Chart را بزن. Metrics، Inspector و Bottom Dock موقتاً پنهان می‌شوند و Chart تقریباً کل صفحه را می‌گیرد.

## کنترل Replay

- `Step Forward`: دقیقاً یک Close Batch
- `Play`: اجرای پیوسته
- `Pause`: توقف
- `Speed`: سرعت Replay
- `Reset`: بازگشت به ابتدا
- Timeline Slider: Seek

## علت رفع Lag

نسخه جدید:

- چند WebSocket Frame پشت‌سرهم را در هر Animation Frame ادغام می‌کند.
- Candleها را Incremental به Chart اضافه می‌کند.
- Indicator Lineها فقط با Point جدید Update می‌شوند.
- React دیگر در هر Frame تمام Chart State را Deep Copy نمی‌کند.
- Window حداکثر 12000 Candle دارد و پس از پرشدن نیز Candle جدید را ادامه می‌دهد.
- Periodic Compaction مانع رشد بی‌پایان State می‌شود.

## اجرای Quality Gate

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\quality.ps1
```

نتیجه مورد انتظار نسخه 1.1.0:

```text
Ruff: passed
Pyright strict: 0 errors
Pytest: 124 passed
Frontend tests: 9 passed
TypeScript: passed
Production build: passed
Schema drift: passed
```

## Hard Refresh مرورگر

بعد از Build جدید:

```text
Ctrl + F5
```

اگر تنظیمات Scale قبلی نامناسب بود، داخل DevTools مرورگر Local Storage کلیدهای زیر را پاک کن:

```text
vex.chart.viewport.v2.*
```

یا از دکمه Reset داخل Chart استفاده کن.
