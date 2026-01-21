from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import os
from typing import Dict

app = FastAPI(
    title="EcoFlow API Gateway",
    description="Микросервисная платформа для управления экологическими проектами",
    version="1.0.0"
)

security = HTTPBearer()

# Настройки сервисов
SERVICES = {
    "auth": os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001"),
    "projects": os.getenv("PROJECT_SERVICE_URL", "http://project-service:8002"),
    "carbon": os.getenv("CARBON_SERVICE_URL", "http://carbon-service:8003"),
    "monitoring": os.getenv("MONITORING_SERVICE_URL", "http://monitoring-service:8004"),
}

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Проверка JWT токена"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{SERVICES['auth']}/verify",
                headers={"Authorization": f"Bearer {credentials.credentials}"}
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            return response.json()
        except:
            raise HTTPException(status_code=503, detail="Auth service unavailable")

@app.get("/")
async def root():
    return {
        "message": "Welcome to EcoFlow API",
        "version": "1.0.0",
        "services": list(SERVICES.keys())
    }

@app.get("/health")
async def health_check():
    """Проверка здоровья всех сервисов"""
    health_status = {"gateway": "healthy"}
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for service_name, url in SERVICES.items():
            try:
                response = await client.get(f"{url}/health")
                health_status[service_name] = "healthy" if response.status_code == 200 else "unhealthy"
            except:
                health_status[service_name] = "unreachable"
    
    return health_status

@app.post("/api/projects")
async def create_project(
    project_data: Dict,
    user_data: Dict = Depends(verify_token)
):
    """Создание нового экологического проекта"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SERVICES['projects']}/projects",
            json={**project_data, "created_by": user_data["user_id"]},
            headers={"X-User-Id": str(user_data["user_id"])}
        )
        return response.json()

@app.get("/api/dashboard")
async def get_dashboard(user_data: Dict = Depends(verify_token)):
    """Получение данных для dashboard"""
    async with httpx.AsyncClient() as client:
        projects_response = await client.get(
            f"{SERVICES['projects']}/projects/user/{user_data['user_id']}"
        )
        carbon_response = await client.get(
            f"{SERVICES['carbon']}/footprint/{user_data['user_id']}"
        )
        
        return {
            "projects": projects_response.json(),
            "carbon_footprint": carbon_response.json()
        }
