import json, hashlib
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from .models import *

DEFAULTS={'key_prefix':'ALi','plans':{'1d':{'days':1,'cost':1},'7d':{'days':7,'cost':7},'30d':{'days':30,'cost':30},'90d':{'days':90,'cost':90},'lifetime':{'days':None,'cost':500}},'packages':{'starter':{'credits':100,'amount':10000},'studio':{'credits':500,'amount':45000}}}
def settings(db):
    row=db.get(Setting,'platform')
    return json.loads(row.value) if row else json.loads(json.dumps(DEFAULTS))
def audit(db,actor,action,details): db.add(Audit(actor_id=actor,action=action,details=str(details)[:500]))
def wallet(db,uid):
    w=db.scalar(select(Wallet).where(Wallet.user_id==uid).with_for_update())
    if not w: raise HTTPException(404,'Wallet not found')
    return w
def change_balance(db,user_id,actor,amount,kind,reference,reason):
    w=wallet(db,user_id)
    if w.balance+amount<0: raise HTTPException(409,'Insufficient credits')
    if w.balance+amount>9_000_000_000_000_000: raise HTTPException(409,'Wallet exceeds safe integer range')
    w.balance+=amount
    db.add(CreditTransaction(user_id=user_id,actor_id=actor,amount=amount,balance_after=w.balance,kind=kind,reference=reference,reason=reason))
    return w.balance

def payload_hash(payload): return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
def prior(db,user,kind,token,payload):
    # Caller locks the same user's wallet before testing/creating operations.
    row=db.scalar(select(Operation).where(Operation.user_id==user,Operation.kind==kind,Operation.token==token).with_for_update())
    if row:
        if row.payload_hash!=payload_hash(payload): raise HTTPException(409,'Operation ID already used for different input')
        return json.loads(row.result)
def remember(db,user,kind,token,payload,result):
    db.add(Operation(user_id=user,kind=kind,token=token,payload_hash=payload_hash(payload),result=json.dumps(result)))
    return result

def iso(value): return value.isoformat(timespec='seconds')+'Z' if value else None
def license_status(l):
    if l.state!='enabled':return l.state
    if l.expires_at and l.expires_at<=now():return 'expired'
    return 'active' if l.activated_at else 'unactivated'
def license_json(db,l):
    return {'id':l.id,'key':l.key,'owner_id':l.owner_id,'plan':l.plan,'device_limit':l.device_limit,'devices':db.scalar(select(func.count()).select_from(Device).where(Device.license_id==l.id)),'status':license_status(l),'created_at':iso(l.created_at),'activated_at':iso(l.activated_at),'expiry':iso(l.expires_at) if l.duration_days is not None else 'Lifetime'}
def owned_license(db,user,lid,lock=False):
    stmt=select(License).where(License.id==lid)
    if user.role!='owner':stmt=stmt.where(License.owner_id==user.id)
    if lock:stmt=stmt.with_for_update()
    l=db.scalar(stmt)
    if not l:raise HTTPException(404,'License not found')
    return l

def payment_json(p):
    return {'id':p.id,'user_id':p.user_id,'method':p.method,'package':p.package,'credits':p.credits,'amount':p.amount,'currency':p.currency,'reference':p.reference,'gateway_order':p.gateway_order,'status':p.state,'reason':p.decision_reason,'created_at':iso(p.created_at)}
def approve_payment(db,p,actor,reason):
    if p.state=='approved':return
    if p.state!='pending':raise HTTPException(409,'Payment is not pending')
    change_balance(db,p.user_id,actor,p.credits,'payment','payment:'+str(p.id),reason)
    p.state='approved';p.decision_reason=reason
    audit(db,actor,'payment.approve',str(p.id))
