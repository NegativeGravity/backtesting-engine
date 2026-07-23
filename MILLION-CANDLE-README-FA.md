# بسته Vex Million-Candle Engine 1.5.0

این بسته Redis، Kafka و Elasticsearch اضافه نمی‌کند. راه‌حل در خود مسیر محاسبه، persistence، WebSocket و Dashboard پیاده‌سازی شده است.

## نصب خودکار

از پوشه Extract شده:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\APPLY-MILLION-CANDLE-FIX.ps1 `
  -ProjectRoot "G:\PythonProject\backtesting-engine"
```

## نصب دستی

فایل‌های داخل بسته را با حفظ ساختار مسیر روی پروژه Replace کن و اجرا کن:

```powershell
cd G:\PythonProject\backtesting-engine

docker compose down --remove-orphans
docker compose build --no-cache
docker compose up -d --force-recreate
docker compose ps -a
```

Health:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
Invoke-RestMethod http://127.0.0.1:8000/dashboard-health
```

مرورگر:

```text
http://127.0.0.1:8000
Ctrl + Shift + R
```

## اجرای دیتاست بزرگ

در Launcher:

```text
Run until end: روشن
Dashboard stream: Turbo
Bars per second: 100000
Start paused: خاموش
```

مقدار سرعت یک target است؛ throughput واقعی به Strategy، تعداد orderها، CPU و سرعت storage وابسته است.

در Turbo چارت تک‌تک کندل‌ها را در همان لحظه render نمی‌کند. همه کندل‌ها دقیقاً پردازش می‌شوند، اما UI sample می‌شود و هر پنج ثانیه پنجره دقیق آخر را sync می‌کند. برای بررسی هر بخش از تاریخ، بعد از اتمام Run از Seek/Replay استفاده کن.

## Run جدید

برای تغییرات Engine و Runtime باید containerهای جدید اجرا شوند. برای Strategyهایی که source snapshot دارند، Run جدید بساز.

## بررسی

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\VERIFY-MILLION-CANDLE-FIX.ps1 `
  -ProjectRoot "G:\PythonProject\backtesting-engine"
```
