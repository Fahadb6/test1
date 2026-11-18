# إصلاح نشر Wasmer للواجهة + الـAPI

السبب: الرابط `staticfile-firecraft676.wasmer.app` كان يقدّم ملفات Staticfile فقط، ولهذا `/api/health` و`/api/demo/accounts` يرجعان HTML 404. هذه الحزمة تضيف مدخلًا متوافقًا مع قالب خادم Python الرسمي في Wasmer (`wasmer_src/main.py`) لتشغيل `server.py` وتقديم الواجهة وواجهات API من **الأصل نفسه**. لا ترفع مجلد `public/` وحده بوصفه Static Site.

## طريقة النشر

1. فك `zill-platform-demo.zip` كاملًا. ملفات المشروع موجودة مباشرة في جذر الأرشيف: `app.yaml` و`wasmer.toml` بجانب `server.py` ومجلد `public/`.
2. ثبّت Wasmer CLI وسجّل الدخول للحساب الذي يملك `staticfile-firecraft676.wasmer.app`:
   ```bash
   wasmer login
   ```
3. من جذر المجلد المستخرج نفّذ:
   ```bash
   wasmer deploy
   ```
   يستخدم `app.yaml` المالك `firecraft676` والاسم `staticfile`، ويستخدم الحزمة المحلية (`package: .`) ومدخل Wasmer الرسمي `/src/main.py` لتحديث التطبيق المقصود بدل نشر واجهة Staticfile منفصلة. إذا كان اسم المالك/التطبيق في لوحة Wasmer مختلفًا، عدّلهما في `app.yaml` واسم النطاق في `wasmer.toml` قبل النشر.
4. بعد اكتمال نشر **Python app**، تحقّق أولًا من:
   - `https://staticfile-firecraft676.wasmer.app/api/health` — يجب أن يرجع JSON فيه `status: ok`.
   - `https://staticfile-firecraft676.wasmer.app/api/demo/accounts?role=SUPERVISOR` — يجب أن يرجع JSON لحساب المشرف، لا صفحة 404.
5. افتح صفحة الدخول؛ ستظهر بيانات الحساب التجريبي، ويمكن استخدام زر الدخول المباشر.

`app.yaml` يربط SQLite وملف بيانات دخول العرض بوحدة Wasmer الدائمة `/data`، كي لا تختلف الحسابات عند إعادة تشغيل الخدمة. الخادم مضبوط على HTTP أحادي الخيط لتوافق بيئة WASIX؛ هذا إعداد عرض محدود وليس إعداد إنتاج أو توسع متعدد النسخ. وثائق Wasmer تنبّه إلى قيود استخدام الـvolumes لقواعد البيانات.

## مهم

- الرفع من واجهة **Static Site / Staticfile** لا يشغّل Python، حتى لو احتوى ZIP على `server.py` و`app.yaml`. استخدم Wasmer CLI أو Git deployment الذي يبني `wasmer.toml` كـPython app.
- لا تستخدم حسابات/بيانات حقيقية في هذا التطبيق التجريبي. `ZILL_DEMO_CREDENTIALS=shared` ضروري كي تصل بطاقات الدخول من المتصفح.
- عدّلت مدخل Wasmer ليتبع شكل خادم Python الرسمي ويعمل أحادي الخيط؛ اختبرت المسار محليًا مرتين. لم أنفذ نشرًا على حساب Wasmer، لذلك لا أستطيع اعتماد التشغيل على Wasmer Edge قبل رؤية نتيجة الخادم الفعلية. لا تعتبر النشر منجزًا حتى ينجح فحصا `/api/health` و`/api/demo/accounts` على النطاق بعد تشغيل `wasmer deploy`.
