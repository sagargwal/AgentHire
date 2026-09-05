from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.security import HTTPBearer
from app.routers import jd_builder
from app.routers import auth

app = FastAPI(
    title="AgentHire API",
    description="Company-Aware Agentic JD Intelligence Platform",
    version="1.0.0",
    swagger_ui_init_oauth={},
    openapi_tags=[
        {"name": "auth", "description": "Authentication endpoints"},
        {"name": "jd-builder", "description": "JD Builder agent endpoints"}
    ]
)

# This is what makes the Authorize button appear in Swagger
bearer_scheme = HTTPBearer()

@app.get("/health", tags=["default"])
def health_check():
    return {"status": "ok"}

app.include_router(jd_builder.router)
app.include_router(auth.router)