from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
class Role(Base):
    __tablename__='roles'
    name: Mapped[str]=mapped_column(String(16),primary_key=True)
class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    username: Mapped[str]=mapped_column(String(40),unique=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    role: Mapped[str]=mapped_column(ForeignKey('roles.name'))
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class ResellerProfile(Base):
    __tablename__='reseller_profiles'
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),primary_key=True)
    display_name: Mapped[str]=mapped_column(String(80))
class Wallet(Base):
    __tablename__='credit_wallets'
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),primary_key=True)
    balance: Mapped[int]=mapped_column(BigInteger,default=0)
    __table_args__=(CheckConstraint('balance >= 0',name='wallet_nonnegative'),)
class License(Base):
    __tablename__='licenses'
    id: Mapped[int]=mapped_column(primary_key=True)
    key: Mapped[str]=mapped_column(String(100),unique=True)
    owner_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    plan: Mapped[str]=mapped_column(String(16))
    duration_days: Mapped[int|None]=mapped_column(Integer,nullable=True)
    device_limit: Mapped[int]=mapped_column(Integer)
    state: Mapped[str]=mapped_column(String(16),default='enabled',index=True)
    activated_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now,index=True)
class Device(Base):
    __tablename__='license_devices'
    id: Mapped[int]=mapped_column(primary_key=True)
    license_id: Mapped[int]=mapped_column(ForeignKey('licenses.id'),index=True)
    serial_hash: Mapped[str]=mapped_column(String(64))
    first_seen: Mapped[datetime]=mapped_column(DateTime,default=now)
    last_seen: Mapped[datetime]=mapped_column(DateTime,default=now)
    __table_args__=(UniqueConstraint('license_id','serial_hash',name='unique_device'),)
class CreditTransaction(Base):
    __tablename__='credit_transactions'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    actor_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    amount: Mapped[int]=mapped_column(BigInteger)
    balance_after: Mapped[int]=mapped_column(BigInteger)
    kind: Mapped[str]=mapped_column(String(32))
    reference: Mapped[str]=mapped_column(String(160),unique=True)
    reason: Mapped[str]=mapped_column(String(255))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Operation(Base):
    __tablename__='operations'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    kind: Mapped[str]=mapped_column(String(32))
    token: Mapped[str]=mapped_column(String(100))
    payload_hash: Mapped[str]=mapped_column(String(64))
    result: Mapped[str]=mapped_column(Text)
    __table_args__=(UniqueConstraint('user_id','kind','token',name='unique_operation'),)
class Payment(Base):
    __tablename__='payments'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    method: Mapped[str]=mapped_column(String(16))
    package: Mapped[str]=mapped_column(String(40))
    amount: Mapped[int]=mapped_column(BigInteger)  # integer paise
    currency: Mapped[str]=mapped_column(String(3),default='INR')
    credits: Mapped[int]=mapped_column(BigInteger)
    reference: Mapped[str|None]=mapped_column(String(100),nullable=True,unique=True)
    gateway_order: Mapped[str|None]=mapped_column(String(100),nullable=True,unique=True)
    gateway_payment: Mapped[str|None]=mapped_column(String(100),nullable=True,unique=True)
    state: Mapped[str]=mapped_column(String(16),default='pending',index=True)
    decision_reason: Mapped[str]=mapped_column(String(255),default='')
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Webhook(Base):
    __tablename__='payment_webhooks'
    event_id: Mapped[str]=mapped_column(String(100),primary_key=True)
    payload_hash: Mapped[str]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class VerificationLog(Base):
    __tablename__='license_verification_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    license_id: Mapped[int|None]=mapped_column(ForeignKey('licenses.id'),nullable=True,index=True)
    outcome: Mapped[str]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now,index=True)
class ApiKey(Base):
    __tablename__='api_keys'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    name: Mapped[str]=mapped_column(String(64))
    key_hash: Mapped[str]=mapped_column(String(64),unique=True)
    prefix: Mapped[str]=mapped_column(String(16))
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Setting(Base):
    __tablename__='system_settings'
    name: Mapped[str]=mapped_column(String(64),primary_key=True)
    value: Mapped[str]=mapped_column(Text)
class Audit(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True,index=True)
    action: Mapped[str]=mapped_column(String(100))
    details: Mapped[str]=mapped_column(String(500))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now,index=True)
class AuthSession(Base):
    __tablename__='auth_sessions'
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    refresh_hash: Mapped[str]=mapped_column(String(64),unique=True)
    csrf: Mapped[str]=mapped_column(String(64))
    expires_at: Mapped[datetime]=mapped_column(DateTime)
class RateBucket(Base):
    __tablename__='rate_limits'
    key: Mapped[str]=mapped_column(String(64),primary_key=True)
    hits: Mapped[int]=mapped_column(Integer)
    window: Mapped[int]=mapped_column(BigInteger)
