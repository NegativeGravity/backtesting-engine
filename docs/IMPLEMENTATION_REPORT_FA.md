# گزارش پیاده‌سازی بهینه‌سازی موتور بک‌تست

## نتیجه کلی

اصلاحات اصلی و کم‌ریسک معماری روی Data Engine، Broker Simulator، Replay Repository، Live Orchestrator، WebSocket pipeline و Dashboard اعمال شده‌اند. تمرکز اصلی روی این بوده است که سرعت و روانی افزایش پیدا کند، بدون اینکه ترتیب علت و معلولی معاملات، جلوگیری از look-ahead یا deterministic بودن نتیجه قربانی شود.

## Data Engine

- واردکردن فایل‌های مستقل به‌صورت هم‌زمان انجام می‌شود.
- مقدار `file_import_workers: 0` حالت خودکار است.
- برای HDD می‌توان مقدار را `1` گذاشت تا head movement و disk thrashing رخ ندهد.
- برای SSD/NVMe می‌توان تعداد workerها را افزایش داد.
- ترتیب گزارش‌ها و audit نهایی مستقل از زمان پایان threadها باقی مانده است.
- نوشتن فایل‌های Parquet همچنان اتمیک است و artifact ناقص جایگزین cache معتبر نمی‌شود.

## Broker Simulator

- حالت Historical Spread به قرارداد اجرا اضافه شد.
- Spread هر کندل از `source_spread_points` گرفته می‌شود.
- fallback، minimum و maximum spread قابل تنظیم است.
- Spread واقعی همان کندل در entry، protection fill، liquidation و محاسبه هزینه استفاده می‌شود.
- حالت Fixed Spread قبلی بدون تغییر نتیجه قابل استفاده است.

## Performance و Latency

- sleep ساده با Deadline Pacer مبتنی بر monotonic clock جایگزین شد.
- زمان پردازش از delay کم می‌شود و replay speed drift کمتری دارد.
- سقف سرعت تا 100,000 bars/s افزایش یافت.
- نرخ اجرای Engine از نرخ رندر Dashboard جدا شد.
- نرخ publish بر اساس سرعت بین حدود 8 تا 30 فریم در ثانیه تنظیم می‌شود و bars/events میان آن‌ها coalesce می‌شوند.
- اگر تعداد کندل‌های incremental یک فریم زیاد شود، به‌جای ارسال payload بسیار بزرگ یک visual reset شامل آخرین 1,000 کندل ارسال می‌شود.
- هنگام pause آخرین state معلق فوراً flush می‌شود.
- account snapshot تکراری در timeline زنده از هر کندل به snapshot دوره‌ای کاهش یافت؛ account فعلی همچنان در frame وجود دارد.

## Replay Repository

- checkpoint دوره‌ای active orders و positions اضافه شد.
- seek/bootstrap وضعیت را از نزدیک‌ترین checkpoint بازسازی می‌کند و فقط delta بعد از آن را replay می‌کند.
- terminal orderها در جدول indexشده مستقل ذخیره می‌شوند.
- اتصال read-only SQLite برای هر thread reuse می‌شود.
- mmap، query-only، cache و busy timeout تنظیم شده‌اند.
- جایگزین‌شدن فایل replay با signature جدید تشخیص داده می‌شود تا connection قدیمی استفاده نشود.
- `timeline_until` به‌جای اولین eventها، آخرین eventهای نزدیک cursor را برمی‌گرداند.
- payload اولیه مرورگر برای trades/fills/timeline محدود شده است تا reconnect باعث انفجار RAM و JSON نشود.

## Frontend و Dashboard

- WebSocket در Web Worker باقی مانده و frameها قبل از ورود به React merge می‌شوند.
- overflow دیگر با حذف خاموش یک event ادامه پیدا نمی‌کند؛ client reconnect و bootstrap کامل دریافت می‌کند.
- state مربوط به orders و positions از `account.updated` authoritative snapshot همگام می‌شود.
- نمودار با آخرین کندل حرکت می‌کند و تعداد کندل قابل مشاهده و right offset ثابت می‌مانند.
- Y-axis در حالت عادی auto-scale است و فقط با انتخاب کاربر lock می‌شود.
- خطای renderer موجب متوقف‌شدن بک‌تست نمی‌شود و chart recovery مستقل اجرا می‌شود.

## نمایش معامله روی چارت

باکس معامله از داده واقعی Broker ساخته می‌شود، نه صرفاً command استراتژی. اطلاعات زیر روی خود باکس قرار گرفته‌اند:

- OPEN time و entry price
- CLOSE/LIVE time و exit/current price
- SL و TP با قیمت
- Net PnL
- LONG/SHORT
- TP HIT
- SL HIT
- LIQUIDATED
- CLOSED
- OPEN
- هشدار INTRABAR AMBIGUOUS

اگر strategy قبلاً برای همان `trade_id` یک risk/reward box ساخته باشد، نسخه تکراری حذف می‌شود.

## Multi-thread و Multi-process

- Thread برای import فایل‌های مستقل و کارهای I/O/coordination استفاده شده است.
- Strategy همچنان در process مستقل با spawn اجرا می‌شود.
- runهای مستقل می‌توانند روی processهای مستقل اجرا شوند.
- پردازش کندل‌های یک account به‌صورت موازی انجام نشده، چون ترتیب آن‌ها causal است و parallel mutation نتیجه را اشتباه می‌کند.

## تست‌های اجراشده در محیط تحویل

- Python compileall: موفق
- Broker/contract/pacing/schema targeted tests: 36 تست موفق
- TypeScript syntax parse: 49 فایل موفق
- full frontend build اجرا نشد، چون `node_modules` در محیط آفلاین موجود نبود.
- full replay/data test suite اجرا نشد، چون `polars` و `pyarrow` در محیط آفلاین نصب نبودند.

## Benchmark محلی

روی محیط تحویل با Python 3.13.5 و 50,000 کندل اندازه‌گیری شد:

| سناریو | Throughput | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| Idle broker | حدود 25.5k bars/s | 29 µs | 45 µs | 63 µs |
| Open position | حدود 18.0k bars/s | 44 µs | 70 µs | 106 µs |
| Historical spread | حدود 16.8k bars/s | 45 µs | 82 µs | 121 µs |

این اعداد فقط baseline همین ماشین هستند و تضمین عملکرد روی سیستم دیگر محسوب نمی‌شوند.

## بخش‌هایی که نیازمند فاز معماری جدا هستند

Shared-memory IPC، batch چند کندلی Strategy، snapshot کامل state داخلی strategy، Rust/PyO3 broker kernel و tick/order-book simulation تغییرات کوچک نیستند. پیاده‌سازی سطحی آن‌ها می‌تواند deterministic بودن یا ترتیب broker feedback را خراب کند. قرارداد و مسیر مهاجرت آن‌ها در سند `PERFORMANCE_ARCHITECTURE_V2.md` مشخص شده است و باید همراه benchmark و MT5 differential tests توسعه داده شوند.
