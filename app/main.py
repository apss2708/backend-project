from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import jobs
from app.core.logging import setup_logging
from app.core.database import Base, engine

# Initialize log configuration
setup_logging()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup (ensures reviewer setup works with zero manual migrations)
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline",
    description="Asynchronous processing of financial transactions using FastAPI, Celery, and PostgreSQL.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(jobs.router)

@app.get("/")
def read_root():
    return {
        "name": "Transaction Processing Pipeline API",
        "status": "online",
        "documentation_url": "/docs"
    }
