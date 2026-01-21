from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import Optional
import jwt
from passlib.context import CryptContext
import databases
import sqlalchemy
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="EcoFlow Auth Service")

# Настройки
SECRET_KEY = os.getenv("SECRET_KEY", "ecoflow-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# База данных
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./auth.db")
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# Таблица пользователей
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String(100), unique=True, index=True),
    sqlalchemy.Column("username", sqlalchemy.String(50)),
    sqlalchemy.Column("hashed_password", sqlalchemy.String(200)),
    sqlalchemy.Column("organization", sqlalchemy.String(100)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("is_active", sqlalchemy.Boolean, default=True)
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# Хэширование паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Модели
class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    organization: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "auth-service"}

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@app.post("/register", response_model=Token)
async def register(user: UserCreate):
    # Проверка существования пользователя
    query = users.select().where(users.c.email == user.email)
    existing_user = await database.fetch_one(query)
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Создание пользователя
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        email=user.email,
        username=user.username,
        hashed_password=hashed_password,
        organization=user.organization
    )
    user_id = await database.execute(query)
    
    # Создание токена
    access_token = create_access_token(
        data={"sub": user.email, "user_id": user_id}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user_id
    }

@app.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    query = users.select().where(users.c.email == credentials.email)
    user = await database.fetch_one(query)
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token = create_access_token(
        data={"sub": user.email, "user_id": user.id}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id
    }

@app.post("/verify")
async def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user_id": payload["user_id"], "email": payload["sub"]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    query = users.select().where(users.c.id == user_id)
    user = await database.fetch_one(query)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "organization": user.organization,
        "created_at": user.created_at
    }
