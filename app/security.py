import hashlib, secrets, time
from datetime import timedelta
import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .config import get_settings
from .database import get_db
from .models import User, AuthSession, RateBucket, ApiKey, now

passwords=PasswordHash.recommended()
DUMMY=passwords.hash(secrets.token_urlsafe(24))
def digest(value: str): return hashlib.sha256(value.encode()).hexdigest()
def limit(db:Session, request:Request, scope:str, maximum:int=60, window:int=300):
    # Independent transaction: rejection must not roll back the rate counter.
    from .database import SessionLocal, engine
    # Called before the request DB transaction starts (route dependencies enforce ordering).
    key=digest(scope+'|'+(request.client.host if request.client else 'unknown'))
    with SessionLocal() as limiter:
        if engine.dialect.name=='sqlite': limiter.connection().exec_driver_sql('BEGIN IMMEDIATE')
        ts=int(time.time())
        from sqlalchemy import case
        values={'key':key,'hits':1,'window':ts}
        expired=RateBucket.window<=ts-window
        if engine.dialect.name=='sqlite':
            from sqlalchemy.dialects.sqlite import insert
            stmt=insert(RateBucket).values(**values).on_conflict_do_update(index_elements=['key'],set_={'hits':case((expired,1),else_=RateBucket.hits+1),'window':case((expired,ts),else_=RateBucket.window)})
        else:
            from sqlalchemy.dialects.mysql import insert
            stmt=insert(RateBucket).values(**values).on_duplicate_key_update(hits=case((expired,1),else_=RateBucket.hits+1),window=case((expired,ts),else_=RateBucket.window))
        limiter.execute(stmt)
        row=limiter.scalar(select(RateBucket).where(RateBucket.key==key).with_for_update())
        exceeded=row.hits>maximum
        if secrets.randbelow(100)==0: limiter.execute(delete(RateBucket).where(RateBucket.window<ts-86400))
        limiter.commit()
    if exceeded: raise HTTPException(429,'Too many requests. Try again later.',headers={'Retry-After':str(window)})

def auth(request:Request, db:Session=Depends(get_db)) -> User:
    settings=get_settings(); bearer=request.headers.get('authorization','')
    token=bearer[7:] if bearer.startswith('Bearer ') else request.cookies.get('ah_access','')
    try:
        claims=jwt.decode(token,settings.jwt_secret,algorithms=['HS256'],options={'require':['exp','sub','sid','typ']})
        if claims['typ']!='access': raise ValueError()
        sess=db.get(AuthSession,claims['sid'])
        if not sess or sess.expires_at<=now() or str(sess.user_id)!=claims['sub']: raise ValueError()
        user=db.get(User,sess.user_id)
        if not user or not user.enabled: raise ValueError()
        if request.method not in ['GET','HEAD','OPTIONS'] and not bearer:
            if not secrets.compare_digest(request.headers.get('x-csrf-token',''),sess.csrf): raise HTTPException(403,'CSRF token required')
        request.state.session=sess
        return user
    except HTTPException: raise
    except (jwt.PyJWTError,ValueError,TypeError,KeyError): raise HTTPException(401,'Sign in required')

def owner(user:User=Depends(auth)):
    if user.role!='owner': raise HTTPException(403,'Owner access required')
    return user

def license_auth(request:Request,db:Session=Depends(get_db)):
    raw=request.headers.get('x-api-key')
    if raw:
        key=db.scalar(select(ApiKey).where(ApiKey.key_hash==digest(raw),ApiKey.enabled.is_(True)))
        user=db.get(User,key.user_id) if key else None
        if not user or not user.enabled: raise HTTPException(401,'Invalid API key')
        request.state.api_key=True
        return user
    return auth(request,db)

def tokens(db:Session,user:User,response):
    cfg=get_settings(); raw=secrets.token_urlsafe(48)
    sess=AuthSession(id=secrets.token_hex(24),user_id=user.id,refresh_hash=digest(raw),csrf=secrets.token_hex(24),expires_at=now()+timedelta(days=cfg.session_days))
    db.add(sess);db.flush()
    access=jwt.encode({'sub':str(user.id),'sid':sess.id,'typ':'access','exp':now()+timedelta(minutes=cfg.access_minutes)},cfg.jwt_secret,algorithm='HS256')
    secure=cfg.app_env=='production'
    response.set_cookie('ah_access',access,httponly=True,secure=secure,samesite='strict',max_age=cfg.access_minutes*60,path='/')
    response.set_cookie('ah_refresh',raw,httponly=True,secure=secure,samesite='strict',max_age=cfg.session_days*86400,path='/api/auth')
    return {'csrf':sess.csrf,'user':{'id':user.id,'username':user.username,'role':user.role}}
