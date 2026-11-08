"""
Da (o quita) permisos de administrador a un usuario.

    python -m scripts.hacer_admin usuario@educastillalamancha.es
    python -m scripts.hacer_admin usuario@educastillalamancha.es --quitar
    python -m scripts.hacer_admin --primero      # el primer usuario registrado, si no hay admins
"""
import argparse
import sys

from app.auth import make_first_user_admin
from app.database import SessionLocal
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", nargs="?")
    parser.add_argument("--quitar", action="store_true", help="quitar permisos en lugar de darlos")
    parser.add_argument("--primero", action="store_true", help="hacer admin al primer usuario si no hay ninguno")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.primero:
            user = make_first_user_admin(db)
            print(f"Admin: {user.email}" if user else "Ya existe un admin (o no hay usuarios).")
            return 0
        if not args.email:
            parser.error("indica un email o --primero")
        user = db.query(User).filter(User.email == args.email).first()
        if not user:
            print(f"No existe ningún usuario con email {args.email} (debe entrar una vez en la web).")
            return 1
        user.is_admin = not args.quitar
        db.commit()
        print(f"{user.email}: is_admin={user.is_admin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
