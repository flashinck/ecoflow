from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime
import databases
import sqlalchemy
import os

app = FastAPI(title="EcoFlow Project Service")

# Настройки базы данных
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./projects.db")
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# Enum для типов проектов
class ProjectType(str, Enum):
    REFORESTATION = "reforestation"
    RENEWABLE_ENERGY = "renewable_energy"
    WASTE_MANAGEMENT = "waste_management"
    WATER_CONSERVATION = "water_conservation"
    BIODIVERSITY = "biodiversity"

class ProjectStatus(str, Enum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"

# Таблица проектов
projects = sqlalchemy.Table(
    "projects",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String(200)),
    sqlalchemy.Column("description", sqlalchemy.Text),
    sqlalchemy.Column("project_type", sqlalchemy.String(50)),
    sqlalchemy.Column("status", sqlalchemy.String(20), default=ProjectStatus.PLANNING),
    sqlalchemy.Column("location", sqlalchemy.String(200)),
    sqlalchemy.Column("budget", sqlalchemy.Float),
    sqlalchemy.Column("start_date", sqlalchemy.DateTime),
    sqlalchemy.Column("end_date", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("created_by", sqlalchemy.Integer),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("co2_reduction_goal", sqlalchemy.Float),  # тонн CO2
    sqlalchemy.Column("area_size", sqlalchemy.Float),  # гектары
    sqlalchemy.Column("current_progress", sqlalchemy.Float, default=0.0),  # процент
)

# Таблица участников проекта
project_members = sqlalchemy.Table(
    "project_members",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("project_id", sqlalchemy.Integer),
    sqlalchemy.Column("user_id", sqlalchemy.Integer),
    sqlalchemy.Column("role", sqlalchemy.String(50)),
    sqlalchemy.Column("joined_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# Модели
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    description: str
    project_type: ProjectType
    location: str
    budget: float = Field(..., gt=0)
    start_date: datetime
    end_date: Optional[datetime] = None
    co2_reduction_goal: float = Field(..., gt=0)
    area_size: float = Field(..., gt=0)

class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    project_type: str
    status: str
    location: str
    budget: float
    start_date: datetime
    end_date: Optional[datetime]
    created_by: int
    created_at: datetime
    co2_reduction_goal: float
    area_size: float
    current_progress: float

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "project-service"}

@app.post("/projects", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, x_user_id: int = Query(...)):
    query = projects.insert().values(
        **project.dict(),
        created_by=x_user_id,
        status=ProjectStatus.PLANNING
    )
    project_id = await database.execute(query)
    
    # Добавляем создателя как участника
    member_query = project_members.insert().values(
        project_id=project_id,
        user_id=x_user_id,
        role="creator"
    )
    await database.execute(member_query)
    
    # Получаем созданный проект
    query = projects.select().where(projects.c.id == project_id)
    created_project = await database.fetch_one(query)
    
    return created_project

@app.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int):
    query = projects.select().where(projects.c.id == project_id)
    project = await database.fetch_one(query)
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return project

@app.get("/projects/user/{user_id}", response_model=List[ProjectResponse])
async def get_user_projects(user_id: int):
    # Получаем проекты, где пользователь является участником
    query = (
        projects.select()
        .join(project_members, projects.c.id == project_members.c.project_id)
        .where(project_members.c.user_id == user_id)
    )
    return await database.fetch_all(query)

@app.get("/projects/type/{project_type}", response_model=List[ProjectResponse])
async def get_projects_by_type(project_type: str):
    query = projects.select().where(projects.c.project_type == project_type)
    return await database.fetch_all(query)

@app.patch("/projects/{project_id}/progress")
async def update_progress(
    project_id: int,
    progress: float = Field(..., ge=0, le=100),
    x_user_id: int = Query(...)
):
    # Проверяем права доступа
    query = project_members.select().where(
        (project_members.c.project_id == project_id) &
        (project_members.c.user_id == x_user_id)
    )
    member = await database.fetch_one(query)
    
    if not member:
        raise HTTPException(status_code=403, detail="Not a project member")
    
    # Обновляем прогресс
    query = (
        projects.update()
        .where(projects.c.id == project_id)
        .values(current_progress=progress)
    )
    await database.execute(query)
    
    # Если прогресс 100%, обновляем статус
    if progress >= 100:
        query = (
            projects.update()
            .where(projects.c.id == project_id)
            .values(status=ProjectStatus.COMPLETED)
        )
        await database.execute(query)
    
    return {"message": "Progress updated successfully"}

@app.get("/stats/co2-reduction")
async def get_co2_reduction_stats():
    """Получение статистики по сокращению CO2"""
    query = sqlalchemy.text("""
        SELECT 
            SUM(co2_reduction_goal) as total_goal,
            SUM(co2_reduction_goal * current_progress / 100) as achieved,
            project_type,
            COUNT(*) as project_count
        FROM projects
        GROUP BY project_type
    """)
    return await database.fetch_all(query)
