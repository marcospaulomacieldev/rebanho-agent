"""Gera o banco de dados sintéticos: `python scripts/seed_data.py [--forcar]`.

Toda a lógica está em `app/db/seed.py`; este arquivo só existe como atalho.
"""

from app.db.seed import main

if __name__ == "__main__":
    raise SystemExit(main())
