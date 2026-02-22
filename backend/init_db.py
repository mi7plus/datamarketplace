# app/init_db.py
from app.db import engine, Base
from app.models import User, DataRequest, Submission, UserProfile

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
print("Database tables created!")