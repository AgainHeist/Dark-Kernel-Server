import json, hmac, hashlib, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.main import app,cfg
from app.database import SessionLocal
from app.models import *
from conftest import sign_in

def op():return str(uuid.uuid4())
def generate(c,h,**kwargs):
    data={'plan':'7d','devices':1,'quantity':1,'operation_id':op(),**kwargs}
    return c.post('/api/licenses/'+('bulk-generate' if data['quantity']>1 else 'generate'),headers=h,json=data)
def verify(c,key,serial='device-one',form=False,**kw):
    p={'game':'FREEFIRE','user_key':key,'serial':serial,'version':'2.0',**kw}
    return c.post('/connect',data=p) if form else c.post('/connect',json=p)
def key(c,h,**kw):
    r=generate(c,h,**kw);assert r.status_code==200,r.text
    return r.json()['items'][0]

def test_auth_csrf_logout(client,owner):
    assert client.post('/api/licenses/generate',json={'plan':'7d','operation_id':op()}).status_code==403
    assert client.get('/api/auth/me').json()['user']['role']=='owner'
    assert client.post('/api/auth/logout',headers=owner).status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'username':'owner','password':'Wrong-password-123!'}).status_code==401

def test_registration_is_owner_only(client,reseller):
    _,h=reseller
    r=client.post('/api/auth/register',headers=h,json={'username':'hacker','password':'Hacker-password-123!'})
    assert r.status_code==403
    assert client.get('/api/admin/resellers').status_code==403
    assert client.get('/api/admin/settings').status_code==403

def test_generation_binding_form_and_json(client,reseller):
    _,h=reseller;l=key(client,h)
    assert l['key'].startswith('ALi-') and l['status']=='unactivated'
    assert client.get('/api/reseller/credits').json()['balance']==993
    r=verify(client,l['key'],form=True).json();assert r['status'] is True
    assert isinstance(r['data']['expiry'],str) and r['data']['seller']=='partner'
    assert verify(client,l['key']).json()['data']['expiry']==r['data']['expiry']
    assert verify(client,l['key'],'another-device').json()['message']=='Device mismatch'
    assert client.get('/api/licenses/'+str(l['id'])).json()['devices']==1

def test_expiry_reset_suspend_revoke(client,owner):
    l=key(client,owner);id=l['id'];value=verify(client,l['key']).json()['data']['expiry']
    assert client.post(f'/api/licenses/{id}/suspend',headers=owner).status_code==200
    assert verify(client,l['key']).json()['message']=='License suspended'
    client.post(f'/api/licenses/{id}/reactivate',headers=owner)
    client.post(f'/api/licenses/{id}/reset-devices',headers=owner)
    assert verify(client,l['key'],'new-device').json()['data']['expiry']==value
    with SessionLocal.begin() as db:db.get(License,id).expires_at=now()-timedelta(seconds=1)
    assert verify(client,l['key']).json()['message']=='Expired license'
    r=client.post(f'/api/licenses/{id}/extend',headers=owner,json={'days':7,'operation_id':op()});assert r.status_code==200
    assert verify(client,l['key'],'new-device').json()['status']
    client.post(f'/api/licenses/{id}/revoke',headers=owner)
    assert verify(client,l['key'],'new-device').json()['message']=='License revoked'
    assert client.post(f'/api/licenses/{id}/reactivate',headers=owner).status_code==409

def test_lifetime_and_bulk(client,reseller):
    _,h=reseller;l=key(client,h,plan='lifetime')
    assert verify(client,l['key']).json()['data']['expiry']=='Lifetime'
    r=generate(client,h,quantity=3,plan='1d');assert r.status_code==200
    assert len(r.json()['items'])==3 and r.json()['cost']==3
    assert len(set(x['key'] for x in r.json()['items']))==3

def test_generate_idempotent_and_different_input(client,reseller):
    _,h=reseller;token=op()
    a=generate(client,h,operation_id=token);b=generate(client,h,operation_id=token)
    assert a.json()==b.json()
    assert client.get('/api/reseller/credits').json()['balance']==993
    assert generate(client,h,operation_id=token,devices=2).status_code==409

def test_insufficient_balance_rolls_back(client,reseller):
    _,h=reseller
    assert generate(client,h,quantity=100,plan='90d').status_code==409
    assert client.get('/api/reseller/credits').json()['balance']==1000
    assert client.get('/api/licenses').json()['total']==0

def test_ownership_and_scoped_api_key(client,owner):
    l=key(client,owner)
    client.post('/api/admin/resellers',headers=owner,json={'username':'other','password':'Other-password-123!'})
    h=sign_in(client,'other','Other-password-123!')
    assert client.get('/api/licenses').json()['total']==0
    assert client.get(f'/api/licenses/{l["id"]}').status_code==404
    assert client.post(f'/api/licenses/{l["id"]}/revoke',headers=h).status_code==404
    r=client.post('/api/api-keys',headers=h,json={'name':'test integration'});assert r.status_code==200
    raw=r.json()['key'];kid=r.json()['id']
    client.cookies.clear()
    assert client.get('/api/licenses',headers={'X-API-Key':raw}).status_code==200
    assert client.get('/api/admin/resellers',headers={'X-API-Key':raw}).status_code==401
    h=sign_in(client,'other','Other-password-123!');client.delete('/api/api-keys/'+str(kid),headers=h)
    client.cookies.clear();assert client.get('/api/licenses',headers={'X-API-Key':raw}).status_code==401

def test_reseller_disable_preserves_customer_license(client,reseller):
    uid,h=reseller;l=key(client,h)
    oh=sign_in(client)
    assert client.delete('/api/admin/resellers/'+str(uid),headers=oh).status_code==200
    assert verify(client,l['key']).json()['status']
    assert client.post('/api/auth/login',json={'username':'partner','password':'Partner-password-123!'}).status_code==401

def test_credit_adjustments_retry_and_bounds(client,reseller):
    uid,_=reseller;h=sign_in(client);payload={'user_id':uid,'amount':2000,'reason':'Extra credit allocation','operation_id':op()}
    a=client.post('/api/admin/credits/add',headers=h,json=payload);b=client.post('/api/admin/credits/add',headers=h,json=payload)
    assert a.json()==b.json()=={'balance':3000}
    payload.update(amount=3001,operation_id=op())
    assert client.post('/api/admin/credits/deduct',headers=h,json=payload).status_code==409
    with SessionLocal() as db:assert db.get(Wallet,uid).balance==3000

def test_manual_payment_approval_and_duplicate(client,reseller):
    uid,h=reseller;data={'package':'starter','reference':'UTR_TEST_123456','operation_id':op()}
    r=client.post('/api/payments/manual',headers=h,json=data);assert r.status_code==201,r.text
    assert client.post('/api/payments/manual',headers=h,json=data).json()==r.json()
    assert client.post('/api/payments/manual',headers=h,json={**data,'operation_id':op()}).status_code==409
    assert client.get('/api/reseller/credits').json()['balance']==1000
    pid=r.json()['id']
    assert client.post(f'/api/admin/payments/{pid}/approve',headers=h,json={'reason':'Verified by reseller'}).status_code==403
    oh=sign_in(client)
    for _ in range(2):assert client.post(f'/api/admin/payments/{pid}/approve',headers=oh,json={'reason':'Bank receipt independently checked'}).status_code==200
    with SessionLocal() as db:
        assert db.get(Wallet,uid).balance==1100
        assert db.scalar(select(func.count()).select_from(CreditTransaction).where(CreditTransaction.reference=='payment:'+str(pid)))==1
    assert client.post(f'/api/admin/payments/{pid}/reject',headers=oh,json={'reason':'Too late to reject'}).status_code==409

def test_rejected_payment_not_credited(client,reseller):
    uid,h=reseller;r=client.post('/api/payments/manual',headers=h,json={'package':'starter','reference':'UTR_REJECT_123','operation_id':op()});pid=r.json()['id'];oh=sign_in(client)
    assert client.post(f'/api/admin/payments/{pid}/reject',headers=oh,json={'reason':'No matching bank receipt'}).status_code==200
    assert client.post(f'/api/admin/payments/{pid}/approve',headers=oh,json={'reason':'Attempt to approve'}).status_code==409
    with SessionLocal() as db:assert db.get(Wallet,uid).balance==1000

def test_automatic_gateway_not_configured(client,reseller):
    _,h=reseller
    assert client.post('/api/payments/create',headers=h,json={'package':'starter','operation_id':op()}).status_code==503

def test_gateway_order_and_webhook(client,reseller,monkeypatch):
    uid,h=reseller
    for name in ['payment_key_id','payment_secret','payment_webhook_secret']:monkeypatch.setattr(cfg,name,'test_'+name)
    import app.main as main
    class FakeGateway:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kwargs):
            assert url=='https://api.razorpay.com/v1/orders'
            class Result:
                def raise_for_status(self):pass
                def json(self):return {'id':'order_123','amount':10000,'currency':'INR'}
            return Result()
    monkeypatch.setattr(main.httpx,'Client',lambda **kw:FakeGateway())
    payload={'package':'starter','operation_id':op()};r=client.post('/api/payments/create',headers=h,json=payload);assert r.status_code==200,r.text
    assert client.post('/api/payments/create',headers=h,json=payload).json()==r.json()
    pid=r.json()['id']
    entity={'id':'pay_123','order_id':'order_123','amount':10000,'currency':'INR','captured':True,'status':'captured'}
    def hook(entity,event_id='evt_123',valid=True):
        raw=json.dumps({'event':'payment.captured','payload':{'payment':{'entity':entity}}}).encode()
        sig=hmac.new(cfg.payment_webhook_secret.encode(),raw,hashlib.sha256).hexdigest() if valid else 'wrong'
        return client.post('/api/payments/webhook',content=raw,headers={'Content-Type':'application/json','X-Razorpay-Signature':sig,'X-Razorpay-Event-Id':event_id})
    assert hook(entity,valid=False).status_code==401
    assert hook({**entity,'amount':1}).status_code==409
    assert hook(entity).status_code==200
    assert hook(entity).json()['duplicate']
    assert hook(entity,'evt_other').status_code==200
    assert hook({**entity,'id':'pay_other'},'evt_conflict').status_code==409
    with SessionLocal() as db:assert db.get(Wallet,uid).balance==1100

def test_password_change_revokes_sessions_and_refresh(client,owner):
    old_refresh=client.cookies.get('ah_refresh')
    r=client.post('/api/auth/refresh',headers=owner);assert r.status_code==200
    assert client.cookies.get('ah_refresh')!=old_refresh
    h={'X-CSRF-Token':r.json()['csrf']}
    assert client.post('/api/auth/change-password',headers=h,json={'current_password':'Owner-test-password-123!','new_password':'Replacement-password-123!'}).status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'username':'owner','password':'Owner-test-password-123!'}).status_code==401
    assert sign_in(client,'owner','Replacement-password-123!')

def test_settings_export_and_pagination(client,owner):
    original=client.get('/api/admin/settings').json();original['key_prefix']='ALi';original['plans']['7d']['cost']=12
    assert client.patch('/api/admin/settings',headers=owner,json=original).status_code==200
    generate(client,owner,quantity=26)
    a=client.get('/api/licenses').json();b=client.get('/api/licenses?page=2').json()
    assert a['total']==26 and len(a['items'])==25 and len(b['items'])==1
    assert client.get('/api/licenses/export').text.count('ALi-')==26
    assert client.get('/api/admin/dashboard').json()['metrics']['total_licenses']==26
    assert client.get('/api/admin/logs').json()['total']>0

def test_bad_api_and_origin(client):
    for payload in [[],{},None,{'game':'FREEFIRE','serial':False,'user_key':'x','version':'2.0'}]:
        assert client.post('/connect',content=json.dumps(payload),headers={'Content-Type':'application/json'}).json()['status'] is False
    assert verify(client,'bad',version='1.0').json()['message']=='Unsupported version'
    assert verify(client,'bad',serial='unknown_device').json()['status'] is False
    assert client.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={'username':'owner','password':'Owner-test-password-123!'}).status_code==403
    assert client.post('/connect',content='a'*65537).status_code==413

def test_concurrent_generation_no_double_spend(client,reseller):
    uid,h=reseller
    with SessionLocal.begin() as db:db.get(Wallet,uid).balance=7
    access=client.cookies.get('ah_access')
    def purchase(_):
        with TestClient(app) as c:
            return generate(c,{'Authorization':'Bearer '+access}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(purchase,range(2)))
    assert sorted(results)==[200,409]
    with SessionLocal() as db:
        assert db.get(Wallet,uid).balance==0
        assert db.scalar(select(func.count()).select_from(License))==1

def test_concurrent_bind_cannot_exceed_limit(client,owner):
    l=key(client,owner)
    def bind(i):
        with TestClient(app) as c:return verify(c,l['key'],'device-'+str(i)).json()['status']
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(bind,range(2)))
    assert sorted(results)==[False,True]
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Device).where(Device.license_id==l['id']))==1

def test_owner_route_names_are_restricted(client,reseller):
    assert client.get('/api/admin/dashboard').status_code==403
    assert client.get('/api/admin/transactions').status_code==403

def test_concurrent_generation_same_operation(client,reseller):
    uid,_=reseller;access=client.cookies.get('ah_access');token=op()
    def purchase(_):
        with TestClient(app) as c:return generate(c,{'Authorization':'Bearer '+access},operation_id=token).json()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(purchase,range(2)))
    assert results[0]==results[1]
    with SessionLocal() as db:
        assert db.get(Wallet,uid).balance==993
        assert db.scalar(select(func.count()).select_from(License))==1

def test_concurrent_manual_approval_once(client,reseller):
    uid,h=reseller
    p=client.post('/api/payments/manual',headers=h,json={'package':'starter','reference':'CONCURRENT_1234','operation_id':op()}).json()
    sign_in(client);access=client.cookies.get('ah_access')
    def approve(_):
        with TestClient(app) as c:return c.post(f'/api/admin/payments/{p["id"]}/approve',headers={'Authorization':'Bearer '+access},json={'reason':'Independent receipt verified'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(approve,range(2)))==[200,200]
    with SessionLocal() as db:assert db.get(Wallet,uid).balance==1100

def test_login_rate_limit_survives_rejections(client):
    for _ in range(30):assert client.post('/api/auth/login',json={'username':'owner','password':'Wrong-password-123!'}).status_code==401
    r=client.post('/api/auth/login',json={'username':'owner','password':'Wrong-password-123!'})
    assert r.status_code==429 and r.headers['retry-after']=='300'

def test_api_rate_limit_legacy_json(client,monkeypatch):
    from app.security import limit as original
    import app.main as main
    monkeypatch.setattr(main,'limit',lambda db,request,scope,maximum=60:original(db,request,scope,maximum=1))
    assert verify(client,'invalid').json()['message']=='Invalid license'
    r=verify(client,'invalid');assert r.status_code==200 and r.json()=={'status':False,'message':'Too many attempts'}

def test_ledger_matches_balance_and_password_spaces(client,reseller):
    uid,h=reseller;generate(client,h,quantity=4,plan='7d')
    with SessionLocal() as db:
        total=db.scalar(select(func.sum(CreditTransaction.amount)).where(CreditTransaction.user_id==uid))
        assert total==db.get(Wallet,uid).balance==972
    new='  Password-spaces-123!  '
    assert client.post('/api/auth/change-password',headers=h,json={'current_password':'Partner-password-123!','new_password':new}).status_code==200
    assert sign_in(client,'partner',new)

def test_mysql_schema_compiles():
    # Compile-only portability check. NOT a live MySQL transaction/concurrency test.
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects.mysql import dialect
    from app.database import Base
    for table in Base.metadata.sorted_tables:
        ddl=str(CreateTable(table).compile(dialect=dialect()))
        assert 'CREATE TABLE' in ddl

def test_webhook_failed_then_capture_and_event_hash(client,reseller,monkeypatch):
    uid,h=reseller;monkeypatch.setattr(cfg,'payment_webhook_secret','test-webhook-secret')
    with SessionLocal.begin() as db:
        p=Payment(user_id=uid,method='razorpay',package='starter',amount=10000,credits=100,gateway_order='order_later');db.add(p);db.flush();pid=p.id
    def send(event,entity,eid):
        raw=json.dumps({'event':event,'payload':{'payment':{'entity':entity}}}).encode()
        return client.post('/api/payments/webhook',content=raw,headers={'X-Razorpay-Signature':hmac.new(cfg.payment_webhook_secret.encode(),raw,hashlib.sha256).hexdigest(),'X-Razorpay-Event-Id':eid,'Content-Type':'application/json'})
    assert send('payment.captured',None,'malformed').status_code==422
    entity={'id':'pay_failed','order_id':'order_later','amount':10000,'currency':'INR','status':'failed'}
    assert send('payment.failed',entity,'fail-event').status_code==200
    with SessionLocal() as db:assert db.get(Payment,pid).state=='failed' and db.get(Wallet,uid).balance==1000
    captured={**entity,'id':'pay_success','status':'captured','captured':True}
    assert send('payment.captured',captured,'success-event').status_code==200
    assert send('payment.captured',{**captured,'description':'different-content'},'success-event').status_code==409
    with SessionLocal() as db:assert db.get(Payment,pid).state=='approved' and db.get(Wallet,uid).balance==1100
