from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from app.routers import jd_builder
from app.routers import auth
from app.routers import careers

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://agenthire-frontend.vercel.app",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer()

@app.get("/health", tags=["default"])
def health_check():
    return {"status": "ok"}

app.include_router(jd_builder.router)
app.include_router(auth.router)
app.include_router(careers.router)