"""
Grant (or revoke) administrator rights for a user.

    python -m scripts.make_admin user@example.com
    python -m scripts.make_admin user@example.com --revoke
    python -m scripts.make_admin --first      # first registered user, if there are no admins
"""
import argparse
import sys

from app.auth import make_first_user_admin
from app.database import SessionLocal
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", nargs="?")
    parser.add_argument("--revoke", "--quitar", action="store_true", help="revoke rights instead of granting them")
    parser.add_argument("--first", "--primero", action="store_true", help="make the first user an admin if there is none")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.first:
            user = make_first_user_admin(db)
            print(f"Admin: {user.email}" if user else "An admin already exists (or there are no users).")
            return 0
        if not args.email:
            parser.error("give an email or --first")
        user = db.query(User).filter(User.email == args.email).first()
        if not user:
            print(f"No user with email {args.email} (they must sign in to the website once).")
            return 1
        user.is_admin = not args.revoke
        db.commit()
        print(f"{user.email}: is_admin={user.is_admin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
