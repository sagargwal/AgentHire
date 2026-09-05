from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

POSTGRES_URL = "postgresql+psycopg2://nexus_user:nexus_pass@localhost:5432/nexus_health"

postgres_engine = create_engine(POSTGRES_URL)
PostgresSession = sessionmaker(bind=postgres_engine)