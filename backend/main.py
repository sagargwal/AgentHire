from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from app.routers import jd_builder

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}

app.include_router(jd_builder.router)