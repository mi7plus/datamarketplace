from fastapi import Header, HTTPException, Depends
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
import os

SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

def get_current_user(
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    try:
        # Split header
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid auth scheme")

        # Strip extra quotes and whitespace
        token = parts[1].strip().strip("'\"")

        # Decode JWT
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))  # convert back to int for DB lookup
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        # Fetch user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    except JWTError as e:
        print("JWTError:", e)  # logs the exact decode problem
        raise HTTPException(status_code=401, detail="Invalid token")