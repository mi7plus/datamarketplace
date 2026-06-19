# app/seed.py — run once to populate reference data
from app.db import SessionLocal
from app.models import License


LICENSES = [
    {
        "name": "CC BY 4.0",
        "terms": "Creative Commons Attribution 4.0. You may share and adapt with attribution.",
    },
    {
        "name": "CC BY-SA 4.0",
        "terms": "Creative Commons Attribution-ShareAlike 4.0. Derivatives must use the same license.",
    },
    {
        "name": "CC0 1.0",
        "terms": "Public Domain Dedication. No rights reserved.",
    },
    {
        "name": "Proprietary / Platform Terms",
        "terms": "Data use governed by the platform's Terms of Service. Not for redistribution.",
    },
]


def seed_licenses() -> None:
    db = SessionLocal()
    try:
        for lic in LICENSES:
            exists = db.query(License).filter(License.name == lic["name"]).first()
            if not exists:
                db.add(License(**lic))
        db.commit()
        print("Licenses seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_licenses()
