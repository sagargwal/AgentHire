from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from app.models.nexus_company import NexusBase

POSTGRES_URL = "postgresql+psycopg2://nexus_user:nexus_pass@localhost:5432/nexus_health"

postgres_engine = create_engine(POSTGRES_URL)
PostgresSession = sessionmaker(bind=postgres_engine)

def create_tables():
    NexusBase.metadata.create_all(postgres_engine)

if __name__ == "__main__":
    create_tables()
    print("All tables created successfully")