# معماری اجرای بک‌تست چندمیلیون کندلی Vex 1.5.0

## هدف

این نسخه برای این طراحی شده است که طول دیتاست، مصرف حافظه فعال Dashboard و هزینه مسیر زنده را تعیین نکند. موتور می‌تواند داده را به‌صورت ترتیبی و chunk-based از Parquet بخواند، درحالی‌که مرورگر فقط یک پنجره محدود و یک جریان نمونه‌برداری‌شده از وضعیت زنده را دریافت می‌کند.

اصل کلیدی:

```text
سرعت محاسبه بک‌تست != نرخ رندر Dashboard
```

نمایش تک‌تک میلیون‌ها کندل در زمان واقعی، خودِ بک‌تست را به سرعت Canvas و Main Thread مرورگر محدود می‌کند. در حالت Turbo، همه کندل‌ها توسط Strategy و Broker پردازش می‌شوند، اما Dashboard فقط snapshotهای کنترل‌شده و هر پنج ثانیه یک پنجره دقیق از آخرین ۲۴۰۰ کندل دریافت می‌کند. پس از پایان Run، هر نقطه از تاریخ با Replay و Seek دقیق قابل بررسی است.

## گلوگاه‌هایی که حذف شدند

### ۱. رشد O(N) در Broker

نسخه قبلی در snapshot و report زنده، تاریخچه کامل Orders/Fills/Trades را مرتب و fingerprint می‌کرد. با رشد Run، هزینه هر کندل بیشتر می‌شد.

نسخه 1.5.0:

- Strategy snapshot فقط Active Orders و آخرین ۵۱۲ سفارش terminal را می‌بیند.
- `state_snapshot` cache می‌شود.
- هزینه‌ها، برد/باخت، R، Drawdown و تعداد معاملات به‌صورت incremental نگهداری می‌شوند.
- Live report از aggregate counterها ساخته می‌شود.
- فقط گزارش نهایی تاریخچه کامل را materialize می‌کند.
- حافظه Eventهای Broker به tail محدود ۴۰۹۶ رویدادی محدود شده است.

### ۲. IPC در هر کندل

برای Strategyهای trusted مثل YJ، حالت `in_process` اضافه شده است. semantics callbackها همان است، اما serialization و رفت‌وبرگشت multiprocessing در هر کندل حذف می‌شود.

برای Strategy ناشناس یا غیرقابل‌اعتماد همچنان `process` انتخاب درست است.

### ۳. ذخیره Account Event در هر کندل

رویداد `account.updated` هنوز برای رفتار داخلی Broker/Strategy تولید می‌شود، اما دیگر در Timeline زنده و SQLite Replay برای هر کندل ذخیره نمی‌شود.

- Equity: هر ۱۰ execution bar یا رویداد مهم
- Account snapshot: هر ۲۵۰ bar یا رویداد مهم
- SQLite commit: هر ۲۰۴۸ bar

در نتیجه Replay database به تعداد معاملات و نقاط نمونه‌برداری‌شده رشد می‌کند، نه به چند برابر تعداد کندل‌ها.

### ۴. اجرای دوباره Strategy هنگام Finalization

`LiveReplayJournal` در همان اجرای اصلی، Replay SQLite را append می‌کند. پایان Run فقط index، analytics و manifest را می‌سازد و Strategy دوباره از ابتدا اجرا نمی‌شود.

### ۵. فشار WebSocket و Resync

- حالت `auto` در سرعت ۲۰۰۰ bar/s به بالا وارد Turbo می‌شود.
- Turbo حداکثر طبق `ui_snapshot_interval_ms` وضعیت می‌فرستد.
- Queue هر subscriber bounded و latest-wins است؛ پیام قدیمی دور ریخته می‌شود، نه اینکه مرورگر مجبور به resyncهای پی‌درپی شود.
- هر پنج ثانیه پنجره دقیق ۲۴۰۰ کندلی ارسال می‌شود؛ بین آن‌ها فقط newest state/bar به‌روزرسانی می‌شود.
- Timeline قبل از ارسال compact می‌شود.

### ۶. حافظه و رندر Dashboard

حدهای سخت:

```text
Candles فعال          ۲۴۰۰
Points هر Study       ۲۴۰۰
Drawingهای فعال       ۴۰۰۰ با pruning زمانی
Timeline UI           ۲۰۰۰
Orders UI             ۲۰۰۰
Trades UI             ۲۰۰۰
```

Drawing و Studyهایی که از پنجره فعال خارج می‌شوند از state مرورگر حذف می‌شوند. تاریخچه حذف نمی‌شود؛ در Replay SQLite باقی می‌ماند و با Seek/Bootstrap بازسازی می‌شود.

Overlay فقط Drawingهای داخل visible time range را تبدیل و رسم می‌کند. OffscreenCanvas نیز برای rasterization استفاده می‌شود.

## مسیر داده

```text
Partitioned/Canonical Parquet
        ↓ PyArrow batches (65,536 rows)
BarClose iterator با حافظه ثابت
        ↓
Strategy + Broker sequential causal loop
        ↓
Incremental aggregate state
        ├── Live latest-wins snapshots → WebSocket → Dashboard active window
        └── Append-only SQLite journal → Final Replay + Analytics
```

## حالت‌های نمایش

### Auto

- کمتر از ۲۰۰۰ bar/s: Replay
- ۲۰۰۰ bar/s و بالاتر: Turbo

### Replay

برای بررسی دستی و سرعت‌های پایین. updateهای بیشتری به Dashboard می‌رسد.

### Turbo

برای صدها هزار تا میلیون‌ها کندل. تمام محاسبات دقیق انجام می‌شود، ولی UI sample می‌شود تا هیچ‌وقت به bottleneck موتور تبدیل نشود.

تنظیم پیشنهادی:

```json
{
  "speed_bars_per_second": 100000,
  "visualization_mode": "turbo",
  "ui_snapshot_interval_ms": 500,
  "ui_window_bars": 2400,
  "ui_timeline_limit": 2000
}
```

## محدودیت فنی واقعی

یک Run واحد causal است:

```text
bar N → strategy → orders → broker → account → bar N+1
```

بنابراین داخل یک Run نمی‌توان بدون تغییر نتیجه، کندل‌های متوالی را بین چند process تقسیم کرد. بهینه‌سازی درست، حذف allocation/IPC/I/O اضافی و streaming است. چند Run مستقل را می‌توان روی چند worker یا process جدا اجرا کرد.

## استفاده از پروژه مرجع

از repository زیر برای تأیید جهت معماری ایده گرفته شد:

```text
https://github.com/NegativeGravity/backtesting_platfrom
```

ایده‌های استفاده‌شده محدود به تفکیک مسئولیت Backend/Frontend، اجرای long-running job در Backend و responsive ماندن Frontend بود. سورس کامل repository در محیط بسته‌بندی clone نشد؛ بنابراین هیچ ادعایی درباره کپی مستقیم implementation آن وجود ندارد.

## معیار پذیرش

- طول دیتاست نباید باعث رشد Candle/Timeline/Drawing state مرورگر شود.
- Run در Turbo نباید به FPS چارت وابسته باشد.
- Disconnect مرورگر نباید Run را متوقف کند.
- reconnect باید از bootstrap محدود ادامه دهد.
- Finalization نباید Strategy را دوباره اجرا کند.
- Broker snapshot و live report نباید با طول تاریخچه کندتر شوند.
- همه رویدادهای معامله، fill، box و chart command لازم برای Replay دقیق باید در journal باقی بمانند.
