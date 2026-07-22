# اصلاح هم‌زمانی معاملات YJ و جداسازی Stop/Target — نسخه 1.3.0

این بسته سه مشکل تصویر ارسالی را اصلاح می‌کند:

1. بازنشدن معامله روز جدید وقتی معامله روز قبل هنوز باز است؛
2. نسبت‌دادن باکس، Stop یا شماره Leg معامله قبلی به معامله جدید؛
3. مبهم‌شدن Overlay چارت هنگام وجود چند معامله هم‌زمان.

## علت واقعی مشکل

نسخه قبلی از دو لایه محدودیت استفاده می‌کرد:

- سفارش روز جدید دارای `vex.entry.require_flat=true` بود؛
- `run.yaml` فقط یک پوزیشن باز روی نماد را مجاز می‌کرد.

در نتیجه، تا زمانی که معامله قبلی بسته نمی‌شد، معامله روز جدید باز نمی‌شد. علاوه بر آن، Strategy برای تشخیص Reversal از یک متغیر سراسری استفاده می‌کرد. در شرایطی که رویداد بسته‌شدن و بازشدن در یک چرخه به Strategy می‌رسید، پوزیشن جدید ممکن بود به آخرین باکس تقویمی نسبت داده شود، درحالی‌که Stop آن متعلق به زنجیره قبلی بود.

## رفتار نسخه جدید

- حساب در حالت `hedging` باقی می‌ماند.
- هر روز یک Daily Chain مستقل دارد.
- معامله روز قبل می‌تواند باز بماند و معامله روز جدید نیز مستقل باز شود.
- OCO هر روز فقط sibling همان روز را لغو می‌کند.
- هر پوزیشن `chain_id`، `trade_date` و `leg` معتبر خود را از سفارش مبدا حمل می‌کند.
- هر Stop و TP با `position_id` همان پوزیشن متصل است.
- Stop یک معامله فقط همان معامله را می‌بندد.
- Reversal فقط برای همان Chain ساخته می‌شود و مشخصات Chain قبلی یا بعدی را نمی‌گیرد.
- معامله سوم در هر Chain همچنان ممنوع است.
- ریسک هر ورود ۱٪ Balance تحقق‌یافته فعلی است.
- Overlay چارت تاریخ، Chain و Leg را برای هر معامله نمایش می‌دهد.

## تفاوت مهم با نوت‌بوک

نوت‌بوک مرجع فقط یک متغیر سراسری `position` دارد و ورود جدید را فقط وقتی انجام می‌دهد که `position is None` باشد. بنابراین خود نوت‌بوک معاملات هم‌زمان ندارد.

نسخه 1.3.0 قوانین نوت‌بوک را **داخل هر Chain** بدون تغییر حفظ می‌کند، اما بنا بر درخواست، امکان اجرای چند Chain روزانه به‌صورت هم‌زمان را به‌عنوان Extension اضافه می‌کند. پس عبارت دقیق برای این نسخه چنین است:

```text
Notebook-equivalent per-chain logic + parallel daily-chain extension
```

## نصب

ZIP را Extract کن و در پوشه استخراج‌شده اجرا کن:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\APPLY-FIX.ps1 `
  -ProjectRoot "G:\PythonProject\backtesting-engine"
```

این اصلاح به Import مجدد دیتاست نیاز ندارد، اما به Build مجدد Docker نیاز دارد.

## اجرای دستی

فایل‌ها را از ریشه ZIP روی پروژه Replace کن، سپس:

```powershell
cd G:\PythonProject\backtesting-engine

docker compose down --remove-orphans
docker compose build --no-cache
docker compose up -d --force-recreate
```

بعد:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8001/api/engine/strategies/refresh"
```

نسخه Catalog باید `1.3.0` باشد.

## Run جدید الزامی است

Run قبلی را ادامه نده. Runها Strategy و تنظیمات Broker را در زمان ایجاد snapshot می‌کنند.

```powershell
$RunId = "run_yj_parallel_" + (Get-Date -Format "yyyyMMdd_HHmmss")

powershell -ExecutionPolicy Bypass `
  -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId "yj_box_breakout" `
  -RunId $RunId `
  -Speed 3000 `
  -Play
```

پارامتر `MaxCloseBatches` را برای Full Backtest ارسال نکن.

در مرورگر نیز:

```text
Ctrl + Shift + R
```

## کنترل نتیجه

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\VERIFY-AFTER-RUN.ps1 `
  -ProjectRoot "G:\PythonProject\backtesting-engine" `
  -RunId $RunId
```

خروجی باید برای هر پوزیشن این موارد را جدا نشان دهد:

- PositionId
- TradeDate
- ChainId
- Leg
- Entry
- Stop
- Target

## بازگشت به رفتار تک‌پوزیشن نوت‌بوک

برای رفتار دقیق تک‌پوزیشن نوت‌بوک:

```yaml
allow_overlapping_daily_chains: false
```

و در `run.yaml`:

```yaml
max_open_positions: 1
max_symbol_positions: 1
allow_pyramiding: false
```
