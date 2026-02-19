# app/init_db.py
from app.db import engine, Base
from app.models import User, DataRequest, Submission

Base.metadata.create_all(bind=engine)
print("Database tables created!")