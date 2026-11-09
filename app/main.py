import csv, io, json, secrets, hmac, hashlib, logging, time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, delete, func, case
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from .config import get_settings, ROOT
from .database import Base,engine,get_db,SessionLocal
from .models import *
from .schemas import *
from .security import auth, owner, license_auth, tokens, passwords, DUMMY, digest, limit
from .services import *

log=logging.getLogger('again-heist')
log.setLevel(logging.INFO)
if not log.handlers:
    handler=logging.StreamHandler();handler.setFormatter(logging.Formatter('%(message)s'));log.addHandler(handler)
log.propagate=False
cfg=get_settings()
@asynccontextmanager
async def lifespan(app):
    if cfg.app_env!='production':Base.metadata.create_all(engine)
    yield
app=FastAPI(title='Again Heist',version='1.0.0',lifespan=lifespan,docs_url='/api/docs' if cfg.app_env!='production' else None,redoc_url=None)
origins=[s.strip() for s in cfg.cors_origins.split(',') if s.strip()]
if origins:app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Content-Type','X-CSRF-Token','Authorization','X-API-Key'])

@app.middleware('http')
async def protection(request,call_next):
    rid=secrets.token_hex(8);started=time.monotonic()
    origin=request.headers.get('origin')
    same_origin=str(request.base_url).rstrip('/')
    if request.method not in ['GET','HEAD','OPTIONS'] and origin and origin not in [same_origin,*origins]:
        return JSONResponse({'detail':'Origin not permitted'},403)
    if request.method not in ['GET','HEAD','OPTIONS'] and request.url.path.startswith('/api/') and request.url.path!='/api/payments/webhook':
        try:await run_in_threadpool(limit,None,request,'management',600)
        except HTTPException as exc:return JSONResponse({'detail':exc.detail},exc.status_code,headers=exc.headers)
    # Read a bounded body before dispatch. ASGI server timeouts/reverse proxy add further limits.
    if request.method in ['POST','PATCH','PUT']:
        length=request.headers.get('content-length')
        if length and (not length.isdigit() or int(length)>65536):return JSONResponse({'detail':'Request too large'},413)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>65536:return JSONResponse({'detail':'Request too large'},413)
        request._body=bytes(body)
    response=await call_next(request)
    response.headers['X-Request-ID']=rid
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='no-store' if request.url.path.startswith(('/api','/connect')) else 'no-cache'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' https://checkout.razorpay.com; style-src 'self'; img-src 'self' data: https://*.razorpay.com; connect-src 'self' https://api.razorpay.com; frame-src https://api.razorpay.com https://checkout.razorpay.com; base-uri 'none'; form-action 'self'; frame-ancestors 'self' https://arena.ai https://*.arena.ai https://*.e2b.app" if cfg.app_env!='production' else "default-src 'self'; script-src 'self' https://checkout.razorpay.com; style-src 'self'; img-src 'self' data: https://*.razorpay.com; connect-src 'self' https://api.razorpay.com; frame-src https://api.razorpay.com https://checkout.razorpay.com; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    if cfg.app_env=='production':response.headers['Strict-Transport-Security']='max-age=31536000'
    log.info(json.dumps({'event':'http.request','request_id':rid,'method':request.method,'path':request.url.path,'status':response.status_code,'duration_ms':round((time.monotonic()-started)*1000,2)}))
    return response

@app.exception_handler(IntegrityError)
async def integrity(request,exc):return JSONResponse({'detail':'Duplicate or conflicting operation; refresh and retry safely'},409)
@app.exception_handler(SQLAlchemyError)
async def db_error(request,exc):
    log.error('Database operation failed: %s',type(exc).__name__)
    if request.url.path=='/connect':return JSONResponse({'status':False,'message':'Service temporarily unavailable'})
    return JSONResponse({'detail':'Database temporarily unavailable'},503)

def rate_login(request:Request):limit(None,request,'auth',30)
def rate_connect(request:Request):
    try:limit(None,request,'connect',180)
    except HTTPException:return False
    return True

def user_json(db,u):
    w=db.get(Wallet,u.id)
    return {'id':u.id,'username':u.username,'role':u.role,'enabled':u.enabled,'credits':w.balance if w else 0,'created_at':iso(u.created_at)}

@app.get('/health')
def health(db:Session=Depends(get_db)):
    db.execute(select(1));return {'status':'ok','version':app.version}
@app.post('/api/auth/login',dependencies=[Depends(rate_login)])
def login(data:Credentials,response:Response,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.username==data.username))
    valid=passwords.verify(data.password,u.password_hash if u else DUMMY)
    if not u or not valid or not u.enabled:raise HTTPException(401,'Invalid username or password')
    result=tokens(db,u,response);audit(db,u.id,'auth.login','Session created');return result
@app.post('/api/auth/register')
def register(data:Credentials,u:User=Depends(owner),db:Session=Depends(get_db)):
    return create_reseller(data,u,db)
@app.get('/api/auth/me')
def me(request:Request,u:User=Depends(auth),db:Session=Depends(get_db)):
    return {'user':user_json(db,u),'csrf':request.state.session.csrf}
@app.post('/api/auth/refresh',dependencies=[Depends(rate_login)])
def refresh(request:Request,response:Response,db:Session=Depends(get_db)):
    sess=db.scalar(select(AuthSession).where(AuthSession.refresh_hash==digest(request.cookies.get('ah_refresh',''))).with_for_update())
    if not sess or sess.expires_at<=now():raise HTTPException(401,'Session expired')
    if not secrets.compare_digest(request.headers.get('x-csrf-token',''),sess.csrf):raise HTTPException(403,'CSRF token required')
    u=db.get(User,sess.user_id)
    if not u or not u.enabled:raise HTTPException(401,'Account unavailable')
    db.delete(sess);return tokens(db,u,response)
@app.post('/api/auth/logout')
def logout(request:Request,response:Response,u:User=Depends(auth),db:Session=Depends(get_db)):
    db.delete(request.state.session)
    response.delete_cookie('ah_access',path='/');response.delete_cookie('ah_refresh',path='/api/auth')
    return {'message':'Signed out'}
@app.post('/api/auth/change-password')
def change_password(data:PasswordChange,u:User=Depends(auth),db:Session=Depends(get_db)):
    if not passwords.verify(data.current_password,u.password_hash):raise HTTPException(400,'Current password is incorrect')
    u.password_hash=passwords.hash(data.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id==u.id));audit(db,u.id,'auth.password','All sessions revoked')
    return {'message':'Password changed. Sign in again.'}

@app.get('/api/admin/resellers')
def resellers(page:int=Query(1,ge=1),u:User=Depends(owner),db:Session=Depends(get_db)):
    stmt=select(User).where(User.role=='reseller').order_by(User.id.desc())
    return {'items':[user_json(db,r) for r in db.scalars(stmt.offset((page-1)*25).limit(25))], 'total':db.scalar(select(func.count()).select_from(User).where(User.role=='reseller')),'page':page}
@app.post('/api/admin/resellers',status_code=201)
def create_reseller(data:Credentials,u:User=Depends(owner),db:Session=Depends(get_db)):
    if db.scalar(select(User.id).where(User.username==data.username)):raise HTTPException(409,'Username already exists')
    r=User(username=data.username,password_hash=passwords.hash(data.password),role='reseller');db.add(r);db.flush()
    db.add_all([Wallet(user_id=r.id,balance=0),ResellerProfile(user_id=r.id,display_name=r.username)])
    audit(db,u.id,'reseller.create',r.id);return user_json(db,r)
@app.patch('/api/admin/resellers/{uid}')
def update_reseller(uid:int,data:ResellerPatch,u:User=Depends(owner),db:Session=Depends(get_db)):
    r=db.scalar(select(User).where(User.id==uid,User.role=='reseller').with_for_update())
    if not r:raise HTTPException(404,'Reseller not found')
    if data.enabled is not None:r.enabled=data.enabled
    if data.password:r.password_hash=passwords.hash(data.password)
    if data.password or data.enabled is False:db.execute(delete(AuthSession).where(AuthSession.user_id==r.id))
    audit(db,u.id,'reseller.update',r.id);return user_json(db,r)
@app.delete('/api/admin/resellers/{uid}')
def disable_reseller(uid:int,u:User=Depends(owner),db:Session=Depends(get_db)):
    # Soft deletion preserves issued keys, financial history and referential integrity.
    return update_reseller(uid,ResellerPatch(enabled=False),u,db)
@app.get('/api/admin/credits')
def admin_credits(u:User=Depends(owner),db:Session=Depends(get_db)):
    return {'items':[user_json(db,r) for r in db.scalars(select(User).where(User.role=='reseller').limit(100))]}
def adjust(data,u,db,sign):
    r=db.get(User,data.user_id)
    if not r or r.role!='reseller':raise HTTPException(404,'Reseller not found')
    wallet(db,u.id)
    kind='credit.add' if sign==1 else 'credit.deduct'
    payload=data.model_dump(exclude={'operation_id'})
    result=prior(db,u.id,kind,data.operation_id,payload)
    if result is not None:return result
    balance=change_balance(db,r.id,u.id,sign*data.amount,kind,kind+':'+data.operation_id,data.reason)
    audit(db,u.id,kind,f'{r.id}: {sign*data.amount}; {data.reason}')
    return remember(db,u.id,kind,data.operation_id,payload,{'balance':balance})
@app.post('/api/admin/credits/add')
def add_credits(data:CreditAdjust,u:User=Depends(owner),db:Session=Depends(get_db)):return adjust(data,u,db,1)
@app.post('/api/admin/credits/deduct')
def deduct_credits(data:CreditAdjust,u:User=Depends(owner),db:Session=Depends(get_db)):return adjust(data,u,db,-1)
@app.get('/api/reseller/credits')
def balance(u:User=Depends(auth),db:Session=Depends(get_db)):
    return {'balance':db.get(Wallet,u.id).balance,'packages':settings(db)['packages']}
@app.get('/api/reseller/transactions')
@app.get('/api/admin/transactions')
def transactions(request:Request,page:int=Query(1,ge=1),u:User=Depends(auth),db:Session=Depends(get_db)):
    if request.url.path.startswith('/api/admin') and u.role!='owner':raise HTTPException(403,'Owner access required')
    stmt=select(CreditTransaction)
    if u.role!='owner':stmt=stmt.where(CreditTransaction.user_id==u.id)
    total=db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows=db.scalars(stmt.order_by(CreditTransaction.id.desc()).offset((page-1)*25).limit(25))
    return {'items':[{'id':r.id,'user_id':r.user_id,'amount':r.amount,'balance_after':r.balance_after,'kind':r.kind,'reason':r.reason,'created_at':iso(r.created_at)} for r in rows],'total':total,'page':page}

@app.get('/api/settings/public')
def public_settings(db:Session=Depends(get_db)):
    return {**settings(db),'brand':'Again Heist','telegram':'https://t.me/alionera','youtube':'https://youtube.com/@AimTicxon','automatic_payments':bool(cfg.payment_key_id and cfg.payment_secret and cfg.payment_webhook_secret)}
@app.get('/api/admin/settings')
def get_global(u:User=Depends(owner),db:Session=Depends(get_db)):return settings(db)
@app.patch('/api/admin/settings')
def set_global(data:GlobalSettings,u:User=Depends(owner),db:Session=Depends(get_db)):
    try:value=data.checked()
    except ValueError as e:raise HTTPException(422,str(e))
    row=db.get(Setting,'platform')
    if row:row.value=json.dumps(value)
    else:db.add(Setting(name='platform',value=json.dumps(value)))
    audit(db,u.id,'settings.update','Plans, packages or prefix updated');return value

def generate(data,u,db):
    wallet(db,u.id)
    payload=data.model_dump(exclude={'operation_id'})
    result=prior(db,u.id,'generate',data.operation_id,payload)
    if result is not None:return result
    config=settings(db);plan=config['plans'][data.plan];cost=plan['cost']*data.devices*data.quantity
    if u.role!='owner':change_balance(db,u.id,u.id,-cost,'license','generation:'+str(u.id)+':'+data.operation_id,f'{data.quantity} × {data.plan}, {data.devices} devices')
    result=[]
    for _ in range(data.quantity):
        key=config['key_prefix']+'-'+secrets.token_hex(6).upper()+'-'+secrets.token_hex(6).upper()
        l=License(key=key,owner_id=u.id,plan=data.plan,duration_days=plan['days'],device_limit=data.devices);db.add(l);db.flush();result.append(license_json(db,l))
    audit(db,u.id,'license.generate',f'{data.quantity} licenses; cost={0 if u.role=="owner" else cost}')
    return remember(db,u.id,'generate',data.operation_id,payload,{'items':result,'cost':0 if u.role=='owner' else cost})
@app.post('/api/licenses/generate')
def generate_one(data:Generate,u:User=Depends(license_auth),db:Session=Depends(get_db)):
    if data.quantity!=1:raise HTTPException(422,'Use bulk-generate for multiple keys')
    return generate(data,u,db)
@app.post('/api/licenses/bulk-generate')
def generate_bulk(data:Generate,u:User=Depends(license_auth),db:Session=Depends(get_db)):return generate(data,u,db)

def scoped_licenses(u,q='',status=''):
    stmt=select(License)
    if u.role!='owner':stmt=stmt.where(License.owner_id==u.id)
    if q:stmt=stmt.where(License.key.contains(q,autoescape=True))
    if status in ['suspended','revoked']:stmt=stmt.where(License.state==status)
    elif status=='expired':stmt=stmt.where(License.state=='enabled',License.expires_at<=now())
    elif status=='unactivated':stmt=stmt.where(License.state=='enabled',License.activated_at.is_(None))
    elif status=='active':stmt=stmt.where(License.state=='enabled',License.activated_at.is_not(None),(License.expires_at>now())|License.expires_at.is_(None))
    return stmt
@app.get('/api/licenses/export')
def export(q:str=Query('',max_length=100),status:str='',u:User=Depends(license_auth),db:Session=Depends(get_db)):
    rows=db.scalars(scoped_licenses(u,q,status).order_by(License.id.desc()).limit(10000))
    out=io.StringIO();writer=csv.writer(out);writer.writerow(['ID','Key','Owner','Plan','Status','Expiry UTC'])
    for l in rows:writer.writerow([l.id,l.key,l.owner_id,l.plan,license_status(l),iso(l.expires_at) or ('Lifetime' if l.duration_days is None else 'Not activated')])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="again-heist-licenses.csv"'})
@app.get('/api/licenses')
def licenses(q:str=Query('',max_length=100),status:str='',page:int=Query(1,ge=1),u:User=Depends(license_auth),db:Session=Depends(get_db)):
    stmt=scoped_licenses(u,q,status)
    return {'items':[license_json(db,l) for l in db.scalars(stmt.order_by(License.id.desc()).offset((page-1)*25).limit(25))],'total':db.scalar(select(func.count()).select_from(stmt.subquery())),'page':page}
@app.get('/api/licenses/{lid}')
def license_detail(lid:int,u:User=Depends(license_auth),db:Session=Depends(get_db)):
    l=owned_license(db,u,lid)
    return {**license_json(db,l),'bindings':[{'id':d.id,'fingerprint':d.serial_hash[:12],'first_seen':iso(d.first_seen),'last_seen':iso(d.last_seen)} for d in db.scalars(select(Device).where(Device.license_id==lid))]}
def license_action(lid,action,u,db):
    l=owned_license(db,u,lid,True)
    if l.state=='revoked' and action!='revoke':raise HTTPException(409,'Revoked keys cannot be reactivated or reset')
    if action=='reset':db.execute(delete(Device).where(Device.license_id==lid))
    else:l.state={'suspend':'suspended','revoke':'revoked','reactivate':'enabled'}[action]
    audit(db,u.id,'license.'+action,lid);db.flush();return license_json(db,l)
@app.post('/api/licenses/{lid}/suspend')
def suspend(lid:int,u:User=Depends(auth),db:Session=Depends(get_db)):return license_action(lid,'suspend',u,db)
@app.post('/api/licenses/{lid}/reactivate')
def reactivate(lid:int,u:User=Depends(auth),db:Session=Depends(get_db)):return license_action(lid,'reactivate',u,db)
@app.post('/api/licenses/{lid}/revoke')
def revoke(lid:int,u:User=Depends(auth),db:Session=Depends(get_db)):return license_action(lid,'revoke',u,db)
@app.post('/api/licenses/{lid}/reset-devices')
def reset(lid:int,u:User=Depends(auth),db:Session=Depends(get_db)):return license_action(lid,'reset',u,db)
@app.post('/api/licenses/{lid}/extend')
def extend(lid:int,data:Extend,u:User=Depends(owner),db:Session=Depends(get_db)):
    wallet(db,u.id);payload={'license':lid,'days':data.days}
    old=prior(db,u.id,'extend',data.operation_id,payload)
    if old is not None:return old
    l=owned_license(db,u,lid,True)
    if l.duration_days is None:raise HTTPException(409,'Lifetime licenses do not need extension')
    if l.state=='revoked':raise HTTPException(409,'License revoked')
    l.duration_days+=data.days
    if l.activated_at:l.expires_at=max(l.expires_at,now())+timedelta(days=data.days)
    audit(db,u.id,'license.extend',f'{lid}: {data.days} days')
    return remember(db,u.id,'extend',data.operation_id,payload,license_json(db,l))

@app.post('/connect')
async def connect(request:Request,allowed:bool=Depends(rate_connect),db:Session=Depends(get_db)):
    try:
        payload=await request.json() if request.headers.get('content-type','').startswith('application/json') else dict(await request.form())
    except (ValueError,TypeError):payload=None
    return await run_in_threadpool(verify_license_payload,db,payload,allowed)

def verify_license_payload(db,payload,allowed):
    def reject(message,lid=None):
        db.add(VerificationLog(license_id=lid,outcome=message));return {'status':False,'message':message}
    if not allowed:return reject('Too many attempts')
    try:
        if not isinstance(payload,dict):return reject('Invalid request')
        game=payload.get('game');key=payload.get('user_key');serial=payload.get('serial');version=payload.get('version')
        if game!='FREEFIRE' or not isinstance(key,str) or not 1<=len(key)<=100 or not isinstance(serial,str) or not 1<=len(serial)<=512 or serial.strip() in ['', 'unknown_device']:return reject('Invalid request')
        if version!='2.0':return reject('Unsupported version')
    except (ValueError,TypeError):return reject('Invalid request')
    l=db.scalar(select(License).where(License.key==key).with_for_update())
    if not l:return reject('Invalid license')
    if l.state!='enabled':return reject('License '+l.state,l.id)
    ts=now()
    if l.expires_at and l.expires_at<=ts:return reject('Expired license',l.id)
    hashed=hmac.new(cfg.jwt_secret.encode(),serial.encode(),hashlib.sha256).hexdigest()
    device=db.scalar(select(Device).where(Device.license_id==l.id,Device.serial_hash==hashed))
    if not device:
        count=db.scalar(select(func.count()).select_from(Device).where(Device.license_id==l.id))
        if count>=l.device_limit:return reject('Device mismatch',l.id)
        db.add(Device(license_id=l.id,serial_hash=hashed,first_seen=ts,last_seen=ts))
    else:device.last_seen=ts
    if not l.activated_at:
        l.activated_at=ts
        if l.duration_days is not None:l.expires_at=ts+timedelta(days=l.duration_days)
    issuer=db.get(User,l.owner_id);w=db.get(Wallet,l.owner_id)
    db.add(VerificationLog(license_id=l.id,outcome='verified'))
    return {'status':True,'message':'License verified successfully','data':{'expiry':iso(l.expires_at) if l.expires_at else 'Lifetime','seller':issuer.username,'credit':w.balance}}

@app.post('/api/payments/manual',status_code=201)
def manual_payment(data:ManualPayment,u:User=Depends(auth),db:Session=Depends(get_db)):
    wallet(db,u.id);payload=data.model_dump(exclude={'operation_id'})
    old=prior(db,u.id,'payment.manual',data.operation_id,payload)
    if old is not None:return old
    package=settings(db)['packages'].get(data.package)
    if not package:raise HTTPException(422,'Unknown credit package')
    p=Payment(user_id=u.id,method='manual',package=data.package,amount=package['amount'],credits=package['credits'],reference=data.reference);db.add(p);db.flush()
    audit(db,u.id,'payment.submit',p.id)
    return remember(db,u.id,'payment.manual',data.operation_id,payload,payment_json(p))
@app.post('/api/payments/create')
def create_payment(data:CreatePayment,u:User=Depends(auth),db:Session=Depends(get_db)):
    if not(cfg.payment_key_id and cfg.payment_secret and cfg.payment_webhook_secret):raise HTTPException(503,'Automatic payments are not configured. Use manual payment.')
    wallet(db,u.id);payload=data.model_dump(exclude={'operation_id'})
    old=prior(db,u.id,'payment.auto',data.operation_id,payload)
    if old is not None:return old
    package=settings(db)['packages'].get(data.package)
    if not package:raise HTTPException(422,'Unknown credit package')
    p=Payment(user_id=u.id,method='razorpay',package=data.package,amount=package['amount'],credits=package['credits']);db.add(p);db.flush()
    try:
        with httpx.Client(timeout=10) as client:
            res=client.post('https://api.razorpay.com/v1/orders',auth=(cfg.payment_key_id,cfg.payment_secret),json={'amount':p.amount,'currency':'INR','receipt':'ah-'+str(p.id),'notes':{'platform':'Again Heist'}})
            res.raise_for_status();order=res.json()
        if order.get('amount')!=p.amount or order.get('currency')!='INR' or not isinstance(order.get('id'),str) or not 1<=len(order['id'])<=100:raise ValueError('Invalid provider order')
    except (httpx.HTTPError,ValueError):raise HTTPException(502,'Payment gateway unavailable. No credits charged; retry safely.')
    p.gateway_order=order['id'];audit(db,u.id,'payment.order',p.id)
    result={**payment_json(p),'key_id':cfg.payment_key_id}
    return remember(db,u.id,'payment.auto',data.operation_id,payload,result)
@app.get('/api/payments/history')
def payment_history(page:int=Query(1,ge=1),u:User=Depends(auth),db:Session=Depends(get_db)):
    stmt=select(Payment)
    if u.role!='owner':stmt=stmt.where(Payment.user_id==u.id)
    return {'items':[payment_json(p) for p in db.scalars(stmt.order_by(Payment.id.desc()).offset((page-1)*25).limit(25))],'total':db.scalar(select(func.count()).select_from(stmt.subquery())),'page':page}
@app.post('/api/admin/payments/{pid}/approve')
def approve(pid:int,data:Reason,u:User=Depends(owner),db:Session=Depends(get_db)):
    p=db.scalar(select(Payment).where(Payment.id==pid).with_for_update())
    if not p:raise HTTPException(404,'Payment not found')
    if p.method!='manual':raise HTTPException(409,'Gateway payments require a verified webhook')
    approve_payment(db,p,u.id,data.reason);return payment_json(p)
@app.post('/api/admin/payments/{pid}/reject')
def reject_payment(pid:int,data:Reason,u:User=Depends(owner),db:Session=Depends(get_db)):
    p=db.scalar(select(Payment).where(Payment.id==pid).with_for_update())
    if not p:raise HTTPException(404,'Payment not found')
    if p.method!='manual' or p.state!='pending':raise HTTPException(409,'Only pending manual payments can be rejected')
    p.state='rejected';p.decision_reason=data.reason;audit(db,u.id,'payment.reject',pid);return payment_json(p)
@app.post('/api/payments/webhook')
async def webhook(request:Request,db:Session=Depends(get_db)):
    return await run_in_threadpool(process_webhook,await request.body(),request.headers.get('x-razorpay-signature',''),request.headers.get('x-razorpay-event-id',''),db)

def process_webhook(body,signature,eid,db):
    if not cfg.payment_webhook_secret:raise HTTPException(503,'Webhooks not configured')
    expected=hmac.new(cfg.payment_webhook_secret.encode(),body,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature):raise HTTPException(401,'Invalid webhook signature')
    if not 1<=len(eid)<=100:raise HTTPException(422,'Event ID required')
    try:payload=json.loads(body);event=payload.get('event');entity=payload['payload']['payment']['entity']
    except (ValueError,KeyError,TypeError,AttributeError):raise HTTPException(422,'Malformed webhook')
    if event not in ['payment.captured','payment.failed']:return {'received':True,'ignored':True}
    if not isinstance(entity,dict) or not isinstance(entity.get('order_id'),str) or not 1<=len(entity['order_id'])<=100:raise HTTPException(422,'Malformed payment entity')
    p=db.scalar(select(Payment).where(Payment.gateway_order==entity.get('order_id')).with_for_update())
    if not p:raise HTTPException(404,'Order not found')
    prior_event=db.get(Webhook,eid);hashed=hashlib.sha256(body).hexdigest()
    if prior_event:
        if prior_event.payload_hash!=hashed:raise HTTPException(409,'Event ID content mismatch')
        return {'received':True,'duplicate':True}
    if p.method!='razorpay' or entity.get('amount')!=p.amount or entity.get('currency')!=p.currency:raise HTTPException(409,'Payment amount/currency mismatch')
    if event=='payment.captured':
        if entity.get('status')!='captured' or entity.get('captured') is not True or not isinstance(entity.get('id'),str) or not 1<=len(entity['id'])<=100:raise HTTPException(422,'Payment is not captured')
        if p.gateway_payment and p.gateway_payment!=entity['id']:raise HTTPException(409,'Order already credited')
        if p.state=='failed':p.state='pending' # legitimate later successful attempt for the same order
        approve_payment(db,p,p.user_id,'Verified Razorpay webhook');p.gateway_payment=entity['id']
    elif p.state=='pending':p.state='failed';p.decision_reason='Gateway reported payment failure'
    db.add(Webhook(event_id=eid,payload_hash=hashed));return {'received':True}

@app.get('/api/admin/dashboard')
@app.get('/api/reseller/dashboard')
def dashboard(request:Request,u:User=Depends(auth),db:Session=Depends(get_db)):
    if request.url.path.startswith('/api/admin') and u.role!='owner':raise HTTPException(403,'Owner access required')
    criteria=[] if u.role=='owner' else [License.owner_id==u.id]
    totals=db.execute(select(
        func.count(License.id),
        func.sum(case(( (License.state=='enabled') & License.activated_at.is_not(None) & ((License.expires_at>now())|License.expires_at.is_(None)),1),else_=0)),
        func.sum(case(((License.state=='enabled') & (License.expires_at<=now()),1),else_=0)),
        func.sum(case(((License.state=='enabled') & License.activated_at.is_(None),1),else_=0)),
        func.sum(case((License.state=='suspended',1),else_=0)),
        func.sum(case((License.state=='revoked',1),else_=0)),
    ).where(*criteria)).one()
    paycriteria=[] if u.role=='owner' else [Payment.user_id==u.id]
    txcriteria=[] if u.role=='owner' else [CreditTransaction.user_id==u.id]
    pending,revenue=db.execute(select(func.sum(case((Payment.state=='pending',1),else_=0)),func.sum(case((Payment.state=='approved',Payment.amount),else_=0))).where(*paycriteria)).one()
    issued,used=db.execute(select(func.sum(case((CreditTransaction.amount>0,CreditTransaction.amount),else_=0)),func.sum(case((CreditTransaction.kind=='license',-CreditTransaction.amount),else_=0))).where(*txcriteria)).one()
    metrics=dict(zip(['total_licenses','active_licenses','expired_licenses','unactivated','suspended','revoked'],[n or 0 for n in totals]))
    metrics.update(credits=db.get(Wallet,u.id).balance,pending_payments=pending or 0,revenue_paise=revenue or 0,credits_issued=issued or 0,credits_used=used or 0)
    if u.role=='owner':metrics.update(total_resellers=db.scalar(select(func.count()).select_from(User).where(User.role=='reseller')),active_resellers=db.scalar(select(func.count()).select_from(User).where(User.role=='reseller',User.enabled.is_(True))))
    cutoff=now().replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=6)
    daily={str(day):count for day,count in db.execute(select(func.date(License.created_at),func.count()).where(*criteria,License.created_at>=cutoff).group_by(func.date(License.created_at)))}
    trend=[{'date':str((cutoff+timedelta(days=i)).date()),'issued':daily.get(str((cutoff+timedelta(days=i)).date()),0)} for i in range(7)]
    recent=db.scalars(scoped_licenses(u).order_by(License.id.desc()).limit(5))
    return {'metrics':metrics,'trend':trend,'recent':[license_json(db,l) for l in recent]}
@app.get('/api/admin/logs')
def logs(page:int=Query(1,ge=1),u:User=Depends(owner),db:Session=Depends(get_db)):
    return {'items':[{'id':a.id,'actor':a.actor_id,'action':a.action,'details':a.details,'created_at':iso(a.created_at)} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).offset((page-1)*25).limit(25))],'total':db.scalar(select(func.count()).select_from(Audit)),'page':page}
@app.get('/api/api-keys')
def list_keys(u:User=Depends(auth),db:Session=Depends(get_db)):
    return {'items':[{'id':k.id,'name':k.name,'prefix':k.prefix,'enabled':k.enabled} for k in db.scalars(select(ApiKey).where(ApiKey.user_id==u.id))]}
@app.post('/api/api-keys')
def create_key(data:KeyCreate,u:User=Depends(auth),db:Session=Depends(get_db)):
    raw='ah_'+secrets.token_urlsafe(32);k=ApiKey(user_id=u.id,name=data.name,key_hash=digest(raw),prefix=raw[:12]);db.add(k);db.flush();audit(db,u.id,'api_key.create',k.id)
    return {'id':k.id,'key':raw,'message':'Copy now. This secret is displayed once. Scope: role-scoped license read/generate/export only.'}
@app.delete('/api/api-keys/{kid}')
def revoke_key(kid:int,u:User=Depends(auth),db:Session=Depends(get_db)):
    k=db.scalar(select(ApiKey).where(ApiKey.id==kid,ApiKey.user_id==u.id))
    if not k:raise HTTPException(404,'API key not found')
    k.enabled=False;audit(db,u.id,'api_key.revoke',kid);return {'message':'API key revoked'}

app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='assets')
@app.get('/')
def home():return FileResponse(ROOT/'frontend'/'index.html')
@app.get('/login')
@app.get('/panel')
def frontend():return FileResponse(ROOT/'frontend'/'index.html')
