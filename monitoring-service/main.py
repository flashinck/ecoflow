from fastapi import FastAPI
from contextlib import asynccontextmanager
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY
from datetime import datetime
import databases
import sqlalchemy
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus метрики
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP Requests',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP Request latency',
    ['method', 'endpoint']
)

ERROR_COUNT = Counter(
    'http_errors_total',
    'Total HTTP Errors',
    ['method', 'endpoint', 'error_type']
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.connect()
    logger.info("Monitoring service started")
    yield
    # Shutdown
    await database.disconnect()
    logger.info("Monitoring service stopped")

app = FastAPI(
    title="EcoFlow Monitoring Service",
    lifespan=lifespan
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./monitoring.db")
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# Таблица логов
service_logs = sqlalchemy.Table(
    "service_logs",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("service_name", sqlalchemy.String(50)),
    sqlalchemy.Column("log_level", sqlalchemy.String(20)),
    sqlalchemy.Column("message", sqlalchemy.Text),
    sqlalchemy.Column("timestamp", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("metadata", sqlalchemy.JSON),
)

# Таблица метрик
service_metrics = sqlalchemy.Table(
    "service_metrics",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("service_name", sqlalchemy.String(50)),
    sqlalchemy.Column("metric_name", sqlalchemy.String(100)),
    sqlalchemy.Column("metric_value", sqlalchemy.Float),
    sqlalchemy.Column("timestamp", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("labels", sqlalchemy.JSON),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

@app.get("/health")
async def health():
    REQUEST_COUNT.labels(method='GET', endpoint='/health', status='200').inc()
    return {
        "status": "healthy",
        "service": "monitoring-service",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/log")
async def log_message(
    service_name: str,
    log_level: str,
    message: str,
    metadata: dict = None
):
    query = service_logs.insert().values(
        service_name=service_name,
        log_level=log_level,
        message=message,
        metadata=metadata or {}
    )
    await database.execute(query)
    
    # Логируем также в stdout
    logger.info(f"[{service_name}] {log_level}: {message}")
    
    return {"status": "logged"}

@app.post("/metric")
async def record_metric(
    service_name: str,
    metric_name: str,
    metric_value: float,
    labels: dict = None
):
    query = service_metrics.insert().values(
        service_name=service_name,
        metric_name=metric_name,
        metric_value=metric_value,
        labels=labels or {}
    )
    await database.execute(query)
    
    return {"status": "recorded"}

@app.get("/metrics/prometheus")
async def prometheus_metrics():
    """Endpoint для Prometheus"""
    return generate_latest(REGISTRY)

@app.get("/dashboard")
async def get_monitoring_dashboard():
    """Панель мониторинга"""
    
    # Статистика логов
    logs_query = sqlalchemy.text("""
        SELECT 
            service_name,
            log_level,
            COUNT(*) as count
        FROM service_logs
        WHERE timestamp > datetime('now', '-1 hour')
        GROUP BY service_name, log_level
    """)
    
    logs_stats = await database.fetch_all(logs_query)
    
    # Текущие метрики
    metrics_query = sqlalchemy.text("""
        SELECT 
            service_name,
            metric_name,
            AVG(metric_value) as avg_value,
            MAX(metric_value) as max_value
        FROM service_metrics
        WHERE timestamp > datetime('now', '-5 minutes')
        GROUP BY service_name, metric_name
    """)
    
    metrics_stats = await database.fetch_all(metrics_query)
    
    # Статусы сервисов (имитация проверки)
    services_status = {
        "api-gateway": "healthy",
        "auth-service": "healthy",
        "project-service": "healthy",
        "carbon-service": "healthy",
        "monitoring-service": "healthy"
    }
    
    return {
        "services_status": services_status,
        "logs_statistics": logs_stats,
        "metrics": metrics_stats,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/logs/recent")
async def get_recent_logs(limit: int = 100):
    query = (
        service_logs.select()
        .order_by(service_logs.c.timestamp.desc())
        .limit(limit)
    )
    return await database.fetch_all(query)
