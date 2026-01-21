from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime, date
import databases
import sqlalchemy
import os

app = FastAPI(title="EcoFlow Carbon Service")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./carbon.db")
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# Таблица углеродного следа
carbon_footprint = sqlalchemy.Table(
    "carbon_footprint",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer),
    sqlalchemy.Column("date", sqlalchemy.Date, default=date.today),
    sqlalchemy.Column("category", sqlalchemy.String(50)),
    sqlalchemy.Column("emissions", sqlalchemy.Float),  # кг CO2
    sqlalchemy.Column("description", sqlalchemy.String(200)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

# Таблица компенсаций
carbon_offset = sqlalchemy.Table(
    "carbon_offset",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer),
    sqlalchemy.Column("project_id", sqlalchemy.Integer),
    sqlalchemy.Column("amount", sqlalchemy.Float),  # компенсировано CO2 в кг
    sqlalchemy.Column("date", sqlalchemy.Date, default=date.today),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# Модели
class EmissionRecord(BaseModel):
    user_id: int
    category: str = Field(..., max_length=50)
    emissions: float = Field(..., gt=0)  # в кг CO2
    description: str = Field(None, max_length=200)
    date: date = date.today()

class OffsetRecord(BaseModel):
    user_id: int
    project_id: int
    amount: float = Field(..., gt=0)  # компенсировано CO2 в кг
    date: date = date.today()

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "carbon-service"}

@app.post("/emissions")
async def record_emission(emission: EmissionRecord):
    query = carbon_footprint.insert().values(**emission.dict())
    record_id = await database.execute(query)
    return {"id": record_id, "message": "Emission recorded successfully"}

@app.post("/offset")
async def record_offset(offset: OffsetRecord):
    query = carbon_offset.insert().values(**offset.dict())
    record_id = await database.execute(query)
    return {"id": record_id, "message": "Offset recorded successfully"}

@app.get("/footprint/{user_id}")
async def get_carbon_footprint(user_id: int, period: str = "month"):
    """Получение углеродного следа пользователя"""
    
    # Общие выбросы
    if period == "month":
        query = sqlalchemy.text("""
            SELECT 
                category,
                SUM(emissions) as total_emissions,
                strftime('%Y-%m', date) as month
            FROM carbon_footprint
            WHERE user_id = :user_id
            GROUP BY category, strftime('%Y-%m', date)
            ORDER BY month DESC
            LIMIT 6
        """)
    else:
        query = sqlalchemy.text("""
            SELECT 
                category,
                SUM(emissions) as total_emissions,
                date(date) as day
            FROM carbon_footprint
            WHERE user_id = :user_id
            GROUP BY category, date(date)
            ORDER BY day DESC
            LIMIT 30
        """)
    
    emissions = await database.fetch_all(query, values={"user_id": user_id})
    
    # Компенсации
    offset_query = sqlalchemy.text("""
        SELECT 
            SUM(amount) as total_offset,
            date
        FROM carbon_offset
        WHERE user_id = :user_id
        GROUP BY date
        ORDER BY date DESC
        LIMIT 30
    """)
    
    offsets = await database.fetch_all(offset_query, values={"user_id": user_id})
    
    # Расчет чистого следа
    total_emissions = sum([e.total_emissions for e in emissions])
    total_offset = sum([o.total_offset for o in offsets]) if offsets else 0
    net_footprint = total_emissions - total_offset
    
    return {
        "total_emissions": total_emissions,
        "total_offset": total_offset,
        "net_footprint": net_footprint,
        "emissions_by_category": emissions,
        "offsets": offsets
    }

@app.get("/recommendations/{user_id}")
async def get_recommendations(user_id: int):
    """Получение рекомендаций по снижению углеродного следа"""
    query = sqlalchemy.text("""
        SELECT 
            category,
            SUM(emissions) as emissions,
            COUNT(*) as records
        FROM carbon_footprint
        WHERE user_id = :user_id
        GROUP BY category
        ORDER BY emissions DESC
        LIMIT 3
    """)
    
    top_categories = await database.fetch_all(query, values={"user_id": user_id})
    
    recommendations = []
    for category in top_categories:
        if category.category == "transport":
            recommendations.append({
                "category": "transport",
                "suggestion": "Используйте общественный транспорт или велосипед 2 раза в неделю",
                "potential_reduction": 50,  # кг CO2 в месяц
                "priority": "high"
            })
        elif category.category == "energy":
            recommendations.append({
                "category": "energy",
                "suggestion": "Замените лампы на светодиодные",
                "potential_reduction": 20,
                "priority": "medium"
            })
        elif category.category == "food":
            recommendations.append({
                "category": "food",
                "suggestion": "Уменьшите потребление мяса на 30%",
                "potential_reduction": 100,
                "priority": "high"
            })
    
    return {
        "user_id": user_id,
        "recommendations": recommendations,
        "total_potential_reduction": sum([r["potential_reduction"] for r in recommendations])
    }
