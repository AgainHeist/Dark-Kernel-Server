"""Trusted operator tools. Never expose these as public unauthenticated routes."""
import argparse, getpass, sqlite3
from pathlib import Path
from datetime import timedelta
from sqlalchemy import delete,select
from .database import engine,SessionLocal
from .models import AuthSession,RateBucket,VerificationLog,User
from .security import passwords
from .services import audit

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    prune=sub.add_parser('prune');prune.add_argument('--days',type=int,default=90)
    backup=sub.add_parser('backup-sqlite');backup.add_argument('destination')
    sub.add_parser('reset-owner-password')
    args=p.parse_args()
    if args.command=='backup-sqlite':
        if engine.dialect.name!='sqlite':raise SystemExit('Use a MySQL-native backup tool for production')
        target=Path(args.destination).resolve();root=Path(__file__).resolve().parents[1]
        if target.is_relative_to(root):raise SystemExit('Choose a private backup path OUTSIDE the project directory')
        if target.exists():raise SystemExit('Backup destination already exists')
        target.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(engine.url.database) as source,sqlite3.connect(target) as destination:source.backup(destination)
        target.chmod(0o600);print('Private SQLite backup created. Test a restore before relying on it.');return
    with SessionLocal.begin() as db:
        from .models import now
        if args.command=='prune':
            if args.days<7:raise SystemExit('Retain at least 7 days of verification logs')
            db.execute(delete(VerificationLog).where(VerificationLog.created_at<now()-timedelta(days=args.days)))
            db.execute(delete(AuthSession).where(AuthSession.expires_at<now()))
            import time
            db.execute(delete(RateBucket).where(RateBucket.window<int(time.time())-86400))
            print('Expired sessions/rate buckets and old verification logs pruned. Financial/audit records retained.')
        elif args.command=='reset-owner-password':
            owner=db.scalar(select(User).where(User.role=='owner').with_for_update())
            if not owner:raise SystemExit('No owner account exists')
            value=getpass.getpass('New owner password (12–128 characters): ')
            if not 12<=len(value)<=128 or value!=getpass.getpass('Confirm password: '):raise SystemExit('Invalid password or mismatch')
            owner.password_hash=passwords.hash(value);db.execute(delete(AuthSession).where(AuthSession.user_id==owner.id));audit(db,owner.id,'auth.operator_recovery','Owner password reset by trusted CLI operator')
            print('Owner password reset. All owner sessions revoked.')
if __name__=='__main__':main()
