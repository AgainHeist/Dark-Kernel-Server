/* Optional: npm install; npx playwright install chromium; npm run test:browser.
   Starts against a DISPOSABLE running development instance with a bootstrapped owner.
   Set AH_URL, AH_OWNER, AH_PASSWORD. Never target production: creates test records. */
const { chromium }=require('playwright');
const fs=require('fs');
(async()=>{
 const options={headless:true};
 if(process.env.CHROMIUM_EXECUTABLE_PATH)options.executablePath=process.env.CHROMIUM_EXECUTABLE_PATH;
 if(process.env.CHROMIUM_ARGS)options.args=JSON.parse(process.env.CHROMIUM_ARGS);
 const browser=await chromium.launch(options),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const base=process.env.AH_URL||'http://127.0.0.1:8081',password=process.env.AH_PASSWORD;
 if(!password)throw Error('AH_PASSWORD required; use a disposable development instance');
 const artifact=process.env.AH_ARTIFACTS||'/tmp/again-heist-browser';fs.mkdirSync(artifact,{recursive:true});
 let n=0;const errors=[];page.on('pageerror',e=>errors.push(e.message));
 function ok(value,label){if(!value)throw Error(label);console.log('PASS '+(++n)+' '+label);}
 async function screenshot(name){await page.screenshot({path:artifact+'/'+name+'.png',fullPage:true,animations:'disabled'});}
 async function nav(name){await page.locator('.nav-item[data-nav='+name+']').click();await page.locator('#view .loading').waitFor({state:'detached'});}
 async function login(name,pass){await page.goto(base+'/login');await page.locator('[name=username]').fill(name);await page.locator('[name=password]').fill(pass);await page.locator('#login-form .btn').click();await page.locator('.sidebar').waitFor();await page.locator('#view .loading').waitFor({state:'detached'});}
 await page.goto(base);ok((await page.title()).includes('Again Heist'),'Again Heist brand');
 ok(await page.locator('a[href="https://t.me/alionera"]').count()>0,'Telegram destination');
 ok(await page.locator('a[href="https://youtube.com/@AimTicxon"]').count()>0,'YouTube destination');
 await screenshot('landing-desktop');
 for(const width of [360,390,768,1024,1440]){await page.setViewportSize({width,height:1000});ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Landing fits '+width+'px');}
 await page.setViewportSize({width:390,height:844});await screenshot('landing-mobile');
 await page.emulateMedia({reducedMotion:'reduce'});ok(await page.locator('.access-card').evaluate(e=>getComputedStyle(e).animationName)==='none','Reduced motion');
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(base+'/login');await page.fill('[name=username]',process.env.AH_OWNER||'owner');await page.fill('[name=password]','Wrong-password-123!');await page.click('#login-form .btn');await page.locator('.form-error').filter({hasText:'Invalid username'}).waitFor();ok(true,'Login error shown inline');
 await login(process.env.AH_OWNER||'owner',password);ok(await page.locator('.nav-item[data-nav=resellers]').count()===1,'Owner navigation');await screenshot('owner-dashboard');
 for(const view of ['licenses','generate','resellers','payments','transactions','settings','logs','api','profile']){await nav(view);ok(!(await page.locator('#view').textContent()).includes('Could not load this view'),'Owner view '+view);}
 await nav('generate');await page.fill('[name=quantity]','2');await page.click('#generate-form .btn');await page.locator('.created-keys').waitFor();ok(await page.locator('.created-keys code').count()===2,'UI bulk key generation');const key=await page.locator('.created-keys code').first().textContent();ok(key.startsWith('ALi-'),'ALi key format');await page.click('.modal-close');
 const verified=await (await page.request.post(base+'/connect',{form:{game:'FREEFIRE',user_key:key,serial:'browser-test-device',version:'2.0'}})).json();ok(verified.status===true,'Real HTTP legacy form validation');
 await nav('licenses');await page.locator('[data-license]').first().click();await page.locator('.detail-key').waitFor();ok(await page.locator('.detail-grid').count()===1,'License details modal');await page.click('.modal-close');
 await nav('resellers');await page.click('[data-action=new-reseller]');const partner='test_'+Date.now().toString().slice(-8);const partnerPassword='Reseller-test-password-123!';await page.fill('#reseller-form [name=username]',partner);await page.fill('#reseller-form [name=password]',partnerPassword);await page.click('#reseller-form .btn');await page.locator('#modal').waitFor({state:'hidden'});await page.getByText(partner,{exact:true}).waitFor();ok(true,'Reseller created through UI');
 await page.locator('tr').filter({hasText:partner}).locator('[data-credit]').click();await page.fill('#credit-form [name=amount]','100');await page.fill('#credit-form [name=reason]','Browser workflow test');await page.click('#credit-form .btn');await page.locator('#modal').waitFor({state:'hidden'});ok(true,'Credit adjustment through UI');
 await page.click('[data-action=logout]');await login(partner,partnerPassword);ok(await page.locator('.nav-item[data-nav=resellers]').count()===0,'Reseller has no owner navigation');
 await nav('generate');await page.selectOption('[name=plan]','7d');await page.click('#generate-form .btn');await page.locator('.created-keys').waitFor();await page.click('.modal-close');ok(true,'Reseller spends credits through UI');
 await nav('transactions');ok((await page.locator('#view').textContent()).includes('-7'),'Debit visible in ledger');
 for(const view of ['overview','licenses','generate','payments','transactions','api','profile']){await nav(view);ok(!(await page.locator('#view').textContent()).includes('Could not load this view'),'Reseller view '+view);}
 await nav('payments');await page.locator('[data-manual]').first().click();await page.fill('#manual-form [name=reference]','BROWSER_UTR_'+Date.now());await page.click('#manual-form .btn');await page.locator('#modal').waitFor({state:'hidden'});await page.locator('.status-pending').first().waitFor();ok(true,'Manual payment request displayed as pending');
 await nav('overview');await screenshot('reseller-dashboard');
 for(const width of [360,390,768,1024,1440]){await page.setViewportSize({width,height:1000});ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Dashboard fits '+width+'px');}
 await page.setViewportSize({width:390,height:844});await screenshot('reseller-mobile');
 await page.setViewportSize({width:1440,height:1000});await page.click('[data-action=logout]');await login(process.env.AH_OWNER||'owner',password);await nav('payments');
 await page.locator('[data-decision=approve]').first().click();await page.fill('.confirmation input','Test-only manual review approved');await page.click('.confirmation button:not(.ask-cancel)');await page.locator('.status-approved').first().waitFor();ok(true,'Owner approves manual payment through UI');
 await nav('overview');await screenshot('owner-dashboard-populated');
 await nav('api');await page.click('[data-action=new-api-key]');await page.fill('.confirmation input','Browser test integration');await page.click('.confirmation button:not(.ask-cancel)');await page.locator('.detail-key code').waitFor();ok((await page.locator('.detail-key code').textContent()).startsWith('ah_'),'One-time API credential UI');await page.click('.modal-close');
 ok(errors.length===0,'No JavaScript runtime errors');
 fs.writeFileSync(artifact+'/results.json',JSON.stringify({passed:n,errors},null,2));console.log('TOTAL BROWSER CHECKS: '+n);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
