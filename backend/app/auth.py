# app/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
from datetime import datetime, timedelta
import jwt
import os
from dotenv import load_dotenv

from app.schemas import RegisterSchema, LoginSchema, TokenSchema
from app.models import User
from app.db import get_db

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")

router = APIRouter()

@router.post("/register")
def register(data: RegisterSchema, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = bcrypt.hash(data.password)
    user = User(email=data.email, password_hash=hashed, role=data.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"msg": "User registered"}

@router.post("/login", response_model=TokenSchema)
def login(data: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not bcrypt.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    payload = {"sub": user.id, "exp": datetime.utcnow() + timedelta(hours=2)}
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return {"access_token": token}

def get_current_user(token: str = Depends(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401)
        return user
    except:
        raise HTTPException(status_code=401)