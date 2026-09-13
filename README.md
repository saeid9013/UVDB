# UVDB

ربات تلگرام دانلود رسانه با FastAPI، aiogram، Redis/ARQ، PostgreSQL، yt-dlp و FFmpeg.

## اجرای محلی

پیش‌نیازها: Python 3.12، FFmpeg، Redis و PostgreSQL (برای توسعه، SQLite پیش‌فرض است).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

در ترمینال جداگانه Worker را اجرا کنید. بات به‌صورت پیش‌فرض همراه API با polling اجرا می‌شود:

```powershell
arq app.worker.WorkerSettings
```

## Railway

چهار سرویس بسازید: PostgreSQL، Redis و دو سرویس از همین Repository. Start Command سرویس API همان CMD ایمیج است و polling بات نیز در همین سرویس اجرا می‌شود. Start Command سرویس Worker را `arq app.worker.WorkerSettings` قرار دهید. متغیرهای `.env.example` را از Reference Variableهای Railway پر کنید؛ Redis و PostgreSQL را Public نکنید. سرویس API را فعلاً فقط با یک Replica اجرا کنید تا polling بات تکراری نشود.

## حذف فایل

هر درخواست یک پوشه UUID مستقل در `storage/temp` دارد. Context manager آن پوشه را پس از ارسال موفق یا هر نوع خطا پاک می‌کند. Storage دائمی برای فایل رسانه استفاده نمی‌شود.

## محدودیت‌های MVP

بات اطلاعات ویدئو را می‌گیرد و انتخاب تعاملی کیفیت یا MP3 ارائه می‌کند. پنل مدیریت کامل، migrationهای Alembic، quota روزانه و webhook در مرحله تکمیلی افزوده می‌شوند. API مربوط به metadata و صف آماده است.
