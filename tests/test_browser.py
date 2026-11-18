#!/usr/bin/env python3
"""Chromium checks against the running ZILL demo on localhost:3000."""
from playwright.sync_api import sync_playwright
BASE=__import__('os').environ.get('ZILL_TEST_BASE','http://127.0.0.1:3000')
checks=[];errors=[];expected_404=False
def track_console(message):
 if message.type=='error' and not (expected_404 and '404 (Not Found)' in message.text):errors.append(message.text)
def ck(ok,label):
 assert ok,label;checks.append(label);print('PASS',label)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',track_console)
 page.goto(BASE+'/#/');page.locator('.hero h1').wait_for()
 ck(page.locator('.portal-card').count()==3,'public landing exposes three distinct portals')
 ck(page.locator('img[src="/images/vest-concept-illustration.png"]').count()==1,'concept vest illustration in public story')
 page.locator('img[src="/images/vest-concept-illustration.png"]').scroll_into_view_if_needed();page.wait_for_timeout(250)
 img=page.locator('img[src="/images/vest-concept-illustration.png"]');ck(img.evaluate('(e)=>e.complete&&e.naturalWidth>0'),'concept image visibly loads without broken source')
 ck('ليس منتجًا مصنعًا' in page.locator('body').inner_text(),'conceptual imagery is explicitly labeled')
 # The Wasmer Staticfile failure mode must be diagnosed, never parsed as fake JSON.
 expected_404=True
 page.route('**/api/demo/accounts?role=SUPERVISOR',lambda route:route.fulfill(status=404,content_type='text/html',body='<html>404 Not Found</html>'))
 page.goto(BASE+'/#/supervisor/login');page.locator('#demo-status').wait_for();page.wait_for_function('()=>document.querySelector("#demo-status")?.textContent.includes("server.py")')
 ck('server.py' in page.locator('#demo-status').inner_text(),'static-host API 404 explains backend deployment requirement')
 ck(page.locator('.demo-card-pick:disabled').count()==1,'login does not pretend to authenticate without demo API')
 page.unroute('**/api/demo/accounts?role=SUPERVISOR');expected_404=False
 for slug,cardcount in [('company',1),('supervisor',1),('worker',5)]:
  page.goto(BASE+'/#/'+slug+'/login');cards=page.locator('.demo-card-pick:not([disabled])');cards.first.wait_for(timeout=10000)
  ck(cards.count()==cardcount,f'{slug} login directly displays {cardcount} selectable seeded account card(s)')
  for i in range(cardcount):
   if i>0:page.goto(BASE+'/#/'+slug+'/login');page.locator('.demo-card-pick:not([disabled])').first.wait_for(timeout=10000)
   card=page.locator('.demo-card-pick:not([disabled])').nth(i);card.click()
   ck(bool(page.locator('#username').input_value()) and bool(page.locator('#password').input_value()),f'{slug} card {i+1} fills username and password')
   cardbox=page.locator('.demo-card').nth(i);ck(not cardbox.locator('.demo-credentials').evaluate('(e)=>e.hidden') and cardbox.locator('[data-demo-username]').inner_text()==page.locator('#username').input_value() and cardbox.locator('[data-demo-password]').inner_text()==page.locator('#password').input_value(),f'{slug} card {i+1} visibly reveals matching database credentials')
   cardbox.locator('[data-demo-login]').click();page.locator('.app-shell').wait_for(timeout=10000)
   ck(page.locator('.app-page-head h1').count()==1,f'{slug} account {i+1} authenticates into its portal')
   if slug=='worker' and i==3:
    ck('No Active Vest Assigned' in page.locator('body').inner_text(),'expired worker sees explicit no-active-vest state')
   if slug=='worker' and i==4:
    ck('No Active Vest Assigned' in page.locator('body').inner_text(),'unassigned worker sees explicit no-active-vest state')
   page.reload();page.locator('.app-shell').wait_for(timeout=10000);ck(True,f'{slug} account {i+1} session survives refresh')
   if slug=='company' and i==0:
    for route,header in [('company/sites','المواقع'),('company/teams','الفرق'),('company/people','الحسابات والعاملون'),('company/vests','مخزون السترات'),('company/consent','الخصوصية والوصول'),('company/reports','التقارير')]:
     page.locator(f'[data-go="{route}"]').click();page.wait_for_function('(text)=>document.querySelector(".app-page-head h1")?.textContent.includes(text)',arg=header);ck(header in page.locator('.app-page-head h1').inner_text(),f'company operations page {route} renders')
    page.locator('[data-go="company/people"]').click();page.locator('[data-action="new-worker"]').click();page.locator('.modal').wait_for();ck(page.locator('[data-form="worker"]').count()==1,'company add-worker action opens real operational form');page.locator('.modal-close').click()
    page.locator('[data-go="company/overview"]').click()
   if slug=='supervisor' and i==0:
    ck('موقع الظل التجريبي' in page.locator('body').inner_text(),'supervisor dashboard renders assigned site')
    page.locator('[data-go="supervisor/assignments"]').click();page.wait_for_function('()=>location.hash.includes("assignments")');page.locator('.data-table').wait_for();ck(page.locator('.data-table').count()>0,'supervisor assignments/history view renders')
    page.locator('[data-go="supervisor/alerts"]').click();page.wait_for_function('()=>location.hash.includes("alerts")');page.locator('.notice-card').first.wait_for();ck(page.locator('.notice-card').count()>0,'supervisor alert lifecycle view renders')
   if slug=='worker' and i==0:
    ck('ZT-DEMO-01' in page.locator('body').inner_text(),'worker sees own active vest binding')
    page.locator('[data-go="worker/notifications"]').first.click();page.wait_for_function('()=>location.hash.includes("notifications")');page.wait_for_timeout(150);ck('إشعاراتي' in page.locator('.app-page-head h1').inner_text(),'worker notification view renders')
    page.locator('.app-side [data-go="worker/profile"]').click();page.wait_for_function('()=>location.hash.includes("profile")');page.wait_for_timeout(150);ck('profile' in page.locator('body').inner_text().lower() or 'ملفي' in page.locator('body').inner_text(),'worker personal profile view renders')
   page.locator('[data-action="logout"]').first.click();page.locator('.hero').wait_for(timeout=10000);ck(True,f'{slug} account {i+1} logout clears session')
 # Login/landing responsive viewport checks and important images at narrow/wide sizes.
 for width,height in [(1920,1080),(1440,900),(1366,768),(1024,768),(768,1024),(390,844),(360,800)]:
  page.set_viewport_size({'width':width,'height':height});page.goto(BASE+'/#/worker/login');page.locator('.demo-card-pick:not([disabled])').first.wait_for();
  dims=page.evaluate('({w:innerWidth,d:document.documentElement.scrollWidth})');ck(dims['d']<=dims['w']+2,f'worker login responsive at {width}x{height} without horizontal overflow ({dims["d"]}/{dims["w"]})')
  page.goto(BASE+'/#/');page.locator('.hero h1').wait_for();dims=page.evaluate('({w:innerWidth,d:document.documentElement.scrollWidth})');ck(dims['d']<=dims['w']+2,f'public landing responsive at {width}x{height} without horizontal overflow ({dims["d"]}/{dims["w"]})')
 # Role workspace layout, persistent sidebar/mobile navigation, and narrow/wide dashboard overflow.
 for slug,account,title in [('company',0,'نظرة عامة'),('supervisor',0,'نظرة عامة'),('worker',0,'نظرة عامة')]:
  page.goto(BASE+'/#/'+slug+'/login');page.locator('.demo-card-pick:not([disabled])').first.wait_for();page.locator('.demo-card-pick:not([disabled])').first.click();page.locator('.demo-card').first.locator('[data-demo-login]').click();page.locator('.app-shell').wait_for(timeout=10000)
  for width,height in [ (1920,1080),(1440,900),(1366,768),(1024,768),(768,1024),(390,844),(360,800) ]:
   page.set_viewport_size({'width':width,'height':height});dims=page.evaluate('({w:innerWidth,d:document.documentElement.scrollWidth})');ck(dims['d']<=dims['w']+2,f'{slug} dashboard responsive at {width}x{height} without horizontal overflow ({dims["d"]}/{dims["w"]})')
  if slug=='worker':
   page.set_viewport_size({'width':1440,'height':900});ck(page.locator('.app-side [data-go="worker/profile"]').is_visible(),'worker has desktop navigation to personal profile')
   page.set_viewport_size({'width':390,'height':844});ck(page.locator('.worker-mobile-nav button').count()==5,'worker mobile navigation exposes every personal section')
  page.locator('[data-action="logout"]').first.click();page.locator('.hero').wait_for(timeout=10000)
 ck(not errors,'no uncaught browser errors or console errors: '+repr(errors))
 browser.close()
print(f'\n{len(checks)} browser checks passed')
