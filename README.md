# ZILL — ظِل · Desert Shade demo

حزمة تشغيل مستقلة لمنصة ZILL التجريبية: واجهة عربية/إنجليزية، Python HTTP server، وقاعدة SQLite تُنشأ وتُزرع تلقائيًا. لا يحتاج تشغيل التطبيق إلى Node أو خدمة خارجية أو ملف سري مسبق.

> الحسابات والبيانات خيالية للعرض فقط. لا توجد أجهزة أو قياسات ميدانية متصلة، ولا يدل الرسم على منتج مصنع. لا تستخدم إعداد Wasmer/SQLite هذا للإنتاج.

## تنزيل وبناء الحزمة

المصدر نفسه قابل للتشغيل. لإنشاء ZIP نظيف بملفات المشروع مباشرة في جذر الأرشيف:

```bash
python3 build_release.py
```

يخرج `zill-platform-demo.zip` بجانب مجلد المصدر. الحزمة لا تتضمن قاعدة مطوّر أو كلمة مرور أو `.env` خاصًا.

## المتطلبات المحلية

- Python 3.10 أو أحدث، مع الوحدات القياسية المضمنة.
- لا يلزم `npm install` أو `package.json`: الواجهة JavaScript/CSS عاديان ويقدمهما Python server؛ لا توجد خطوة JavaScript build.
- المنفذ الافتراضي 3000. غيّره في `.env` إذا كان مشغولًا.

## الإعداد والتشغيل — Windows

من جذر المجلد بعد فك الضغط:

```bat
copy .env.example .env
py -3 manage.py init-db
py -3 manage.py check
run.bat
```

ثم افتح <http://127.0.0.1:3000>.

## الإعداد والتشغيل — macOS / Linux

```bash
cp .env.example .env
python3 manage.py init-db
python3 manage.py check
./run.sh
```

أو شغّل `python3 server.py` مباشرة؛ عند أول تشغيل ينشئ SQLite ويزرع حسابات العرض تلقائيًا إن لم توجد بيانات. لا توجد مرحلة build منفصلة.

## البيئة والبيانات

`.env.example` هو ملف الإعداد النموذجي؛ انسخه إلى `.env` وعدّل القيم عند الحاجة. يقرأ الخادم `.env` بنفسه دون تثبيت مكتبة dotenv. أهم الإعدادات:

- `PORT` — المنفذ، افتراضيًا `3000`.
- `ZILL_HOST` — افتراضيًا `127.0.0.1` للتشغيل المحلي.
- `ZILL_DB` — افتراضيًا `./data/zill.sqlite3`.
- `ZILL_DEMO_CREDENTIALS` — `local` محليًا، أو `shared` لبطاقات الحسابات في استضافة العرض، أو `off` لتعطيلها.
- `ZILL_DEMO_CREDENTIAL_FILE` — مكان ملف بيانات حسابات العرض؛ لا ترفعه أو تشاركه.
- `ZILL_COOKIE_CROSS_SITE` — اتركه `0`؛ لا تفعّله إلا عند إعداد HTTPS وcross-site proxy.

تشغّل `manage.py init-db` تهيئة المخطط والزرع الأولي، وهو idempotent للقاعدة القائمة. `manage.py check` يتحقق من جداول البيانات والحسابات. يحتوي SQLite على hashes فقط؛ يُنشأ ملف أسرار demo محليًا عند الزرع ويُستبعد من ZIP. في كل بوابة، تكشف بطاقة الحساب الاسم وكلمة المرور وتملأ الحقول، كما يتيح زر الدخول المباشر الدخول بنقرة واحدة.

عند استخدام Wasmer، يضبط `app.yaml` قاعدة SQLite وملف حسابات العرض داخل volume باسم `/data` ليستمرّا بعد إعادة التشغيل. بيانات Demo فقط.

## الاختبارات

اختبار API مع قاعدة مؤقتة:

```bash
python3 tests/test_api.py
```

اختبار حزمة التنزيل نفسها: يبني ZIP، يفكّه في مجلد مستقل، يهيّئ قاعدة جديدة، يشغّل الخادم المستخرج، ثم يجري جولات المتصفح على **ذلك الخادم المستخرج**:

```bash
python3 -m pip install -r requirements-test.txt
python3 -m playwright install chromium
python3 tests/test_release_bundle.py
```

اختبار Wasmer package/entrypoint محليًا:

```bash
python3 tests/test_wasmer_package.py
```

هذا الاختبار محاكاة محلية لمسارات التخزين وإعادة التشغيل، **وليس Wasmer Edge**.

## Wasmer

الطلب إلى `/api/*` يجب أن يصل إلى Python app، لا إلى Staticfile. أُرفق `wasmer.toml` و`app.yaml` ومدخل WASIX في `wasmer_src/main.py`؛ إعداد النطاق الحالي موجّه إلى `firecraft676/staticfile`. بعد تثبيت Wasmer CLI وتسجيل الدخول:

```bash
wasmer login
wasmer deploy
```

**لا ترفع `public/` وحده من واجهة Static Site**؛ لن يُشغّل `server.py` وستبقى API ترجع 404. افحص بعد النشر:

- `/api/health` يجب أن يرجع JSON وHTTP 200.
- `/api/demo/accounts?role=SUPERVISOR` يجب أن يرجع JSON وHTTP 200.

Wasmer Edge نفسه غير متاح لي للتحقق من نشر الحساب أو قراءة سجلاته؛ لذلك لا أصف النشر البعيد بأنه ناجح قبل هذين الفحصين. راجع `DEPLOY_TO_WASMER.md`.

نتائج التحقق المحلي وحدود ما تم التحقق منه موثقة في `TEST_REPORT.md`.

## محتويات المشروع

- `server.py`, `manage.py` — API، الجلسات والصلاحيات، تهيئة/زرع SQLite، وخادم الملفات من أصل واحد.
- `public/` — الموقع والبوابات والرسوم والصور.
- `wasmer.toml`, `app.yaml`, `wasmer_src/` — مدخل وإعداد استضافة Python على Wasmer.
- `tests/` — API، واجهة Chromium، اختبار الحزمة المستخرجة، واختبار إعداد Wasmer المحلي.
