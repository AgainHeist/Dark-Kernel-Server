from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Credentials(Input):
    username: str=Field(pattern=r'^[A-Za-z0-9_]{3,40}$')
    password: str=Field(min_length=12,max_length=128)
class PasswordChange(Input):
    current_password: str=Field(min_length=1,max_length=128)
    new_password: str=Field(min_length=12,max_length=128)
class ResellerPatch(Input):
    enabled: bool|None=None
    password: str|None=Field(default=None,min_length=12,max_length=128)
class CreditAdjust(Input):
    user_id: int=Field(gt=0)
    amount: int=Field(gt=0,le=9_000_000_000_000_000)
    reason: str=Field(min_length=3,max_length=200)
    operation_id: str=Field(min_length=16,max_length=100)
class Generate(Input):
    plan: Literal['1d','7d','30d','90d','lifetime']='7d'
    devices: int=Field(default=1,ge=1,le=5)
    quantity: int=Field(default=1,ge=1,le=100)
    operation_id: str=Field(min_length=16,max_length=100)
class ManualPayment(Input):
    package: str=Field(min_length=1,max_length=40)
    reference: str=Field(pattern=r'^[A-Za-z0-9_-]{6,100}$')
    operation_id: str=Field(min_length=16,max_length=100)
class CreatePayment(Input):
    package: str=Field(min_length=1,max_length=40)
    operation_id: str=Field(min_length=16,max_length=100)
class Reason(Input):
    reason: str=Field(min_length=3,max_length=200)
class Extend(Input):
    days: int=Field(ge=1,le=3650)
    operation_id: str=Field(min_length=16,max_length=100)
class KeyCreate(Input):
    name: str=Field(min_length=1,max_length=64)
class Plan(Input):
    days: int|None=Field(ge=1,le=3650)
    cost: int=Field(ge=1,le=1_000_000)
class Package(Input):
    credits: int=Field(ge=1,le=10_000_000)
    amount: int=Field(ge=100,le=100_000_000)
class GlobalSettings(Input):
    key_prefix: str=Field(default='ALi',pattern=r'^[A-Za-z0-9]{2,12}$')
    plans: dict[str,Plan]
    packages: dict[str,Package]
    def checked(self):
        if set(self.plans)!={'1d','7d','30d','90d','lifetime'}: raise ValueError('All five plans required')
        if self.plans['lifetime'].days is not None: raise ValueError('Lifetime must have null days')
        if any(v.days is None for k,v in self.plans.items() if k!='lifetime'): raise ValueError('Timed plans need days')
        if not 1<=len(self.packages)<=10: raise ValueError('Provide 1–10 packages')
        if any(not 1<=len(k)<=40 or not k.replace('-','').isalnum() for k in self.packages): raise ValueError('Invalid package name')
        return self.model_dump()
