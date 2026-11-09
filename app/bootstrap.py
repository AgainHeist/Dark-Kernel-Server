"""Run after migrations: python -m app.bootstrap (no public setup endpoint)."""
import re
from sqlalchemy import select
from .database import Base,engine,SessionLocal
from .models import Role,User,Wallet
from .security import passwords
from .config import get_settings

def bootstrap():
    cfg=get_settings()
    if not 12<=len(cfg.admin_password)<=128 or not re.fullmatch(r'[A-Za-z0-9_]{3,40}',cfg.admin_username):raise SystemExit('Set ADMIN_USERNAME and strong ADMIN_PASSWORD (12+ characters)')
    if cfg.app_env!='production':Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        for name in ['owner','reseller']:
            if not db.get(Role,name):db.add(Role(name=name))
        db.flush()
        if db.scalar(select(User.id).where(User.role=='owner')):raise SystemExit('Owner already exists. Bootstrap cannot reset credentials.')
        user=User(username=cfg.admin_username,password_hash=passwords.hash(cfg.admin_password),role='owner');db.add(user);db.flush();db.add(Wallet(user_id=user.id,balance=0))
    print('Owner created. Remove ADMIN_PASSWORD from environment after setup.')
if __name__=='__main__':bootstrap()
