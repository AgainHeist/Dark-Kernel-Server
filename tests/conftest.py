import os, tempfile
target=os.environ.get('AH_TEST_DATABASE_URL')
if target:
    from sqlalchemy.engine import make_url
    if not (make_url(target).database or '').startswith('ah_test_'):raise RuntimeError('Test database name must start ah_test_; it will be erased')
os.environ['DATABASE_URL']=target or 'sqlite:///'+tempfile.mktemp(prefix='ah-tests-',suffix='.sqlite')
os.environ['JWT_SECRET']='test-only-secret-not-for-deployment-'+'x'*40
os.environ['APP_ENV']='development'
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base,engine,SessionLocal
from app.models import Role,User,Wallet
from app.security import passwords

@pytest.fixture
def client():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        db.add_all([Role(name='owner'),Role(name='reseller')]);db.flush()
        u=User(username='owner',password_hash=passwords.hash('Owner-test-password-123!'),role='owner');db.add(u);db.flush();db.add(Wallet(user_id=u.id,balance=0))
    with TestClient(app) as client:yield client

def sign_in(client,name='owner',password='Owner-test-password-123!'):
    res=client.post('/api/auth/login',json={'username':name,'password':password})
    assert res.status_code==200,res.text
    return {'X-CSRF-Token':res.json()['csrf']}

@pytest.fixture
def owner(client):return sign_in(client)
@pytest.fixture
def reseller(client,owner):
    r=client.post('/api/admin/resellers',headers=owner,json={'username':'partner','password':'Partner-password-123!'});assert r.status_code==201,r.text
    uid=r.json()['id']
    r=client.post('/api/admin/credits/add',headers=owner,json={'user_id':uid,'amount':1000,'reason':'Initial allocation','operation_id':'initial-credit-allocation-123'});assert r.status_code==200,r.text
    return uid,sign_in(client,'partner','Partner-password-123!')
