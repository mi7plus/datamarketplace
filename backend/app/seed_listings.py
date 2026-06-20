# app/seed_listings.py
#
# Concierge / cold-start tooling: pre-load a few anchor listings so the catalog is
# never empty for the first buyers. Run once against a dev/staging DB:
#
#     python -m app.seed_listings [supplier_email]
#
# Creates the supplier (PROVIDER) if missing, then lists a couple of small sample
# datasets through the same ingest/validation path the API uses.

import io
import csv
import sys
from decimal import Decimal
from datetime import datetime

from app.db import SessionLocal
from app.models import UserAuth, UserRole, Listing
from app.ingest import validate_dataset
from app.storage import get_storage
from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

SPEC = {
    "columns": [
        {"name": "id", "type": "integer", "required": True},
        {"name": "value", "type": "string", "required": True},
    ],
    "unique_key": ["id"],
}

ANCHORS = [
    {"title": "Sample retail SKUs", "unit": "row", "price": "0.50",
     "provenance": "synthetic seed data", "n": 50},
    {"title": "Sample region index", "unit": "row", "price": "0.25",
     "provenance": "synthetic seed data", "n": 80},
]


def _csv(n: int) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "value"])
    for i in range(1, n + 1):
        w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()


def seed(supplier_email: str = "concierge-supplier@rowbound.local") -> int:
    db = SessionLocal()
    created = 0
    try:
        supplier = db.query(UserAuth).filter(UserAuth.email == supplier_email).first()
        if not supplier:
            supplier = UserAuth(
                email=supplier_email,
                password_hash=pwd.hash("seed-" + datetime.utcnow().isoformat()),
                role=UserRole.PROVIDER,
            )
            db.add(supplier)
            db.commit()
            db.refresh(supplier)

        for a in ANCHORS:
            data = _csv(a["n"])
            res = validate_dataset(data, "seed.csv", SPEC)
            key = f"listings/{supplier.id}/seed_{a['title'].split()[0]}.csv"
            loc = get_storage().save(key, data)
            db.add(Listing(
                supplier_id=supplier.id, title=a["title"], unit=a["unit"],
                price_per_unit=Decimal(a["price"]),
                available_quantity=res.validated_amount, validated_amount=res.validated_amount,
                required_format="csv", spec=SPEC, provenance=a["provenance"],
                sample=res.sample, dataset_hash=res.dataset_hash, storage_location=loc,
                key_hashes=res.key_hashes or None, quality_score=res.quality_score,
                pii_report=res.pii_report or None,
                owner_signature=f"seed listing by {supplier_email} at {datetime.utcnow().isoformat()}Z",
            ))
            created += 1
        db.commit()
        return created
    finally:
        db.close()


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "concierge-supplier@rowbound.local"
    n = seed(email)
    print(f"Seeded {n} anchor listing(s) for {email}.")
