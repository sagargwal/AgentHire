from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Connection string: dialect+driver://user:password@host:port/database_name
DATABASE_URL = "mysql+pymysql://agenthire_user:agenthire_pass@localhost:3306/agenthire"

# Engine = manages the pool of actual connections to MySQL. Doesn't connect yet, just knows how to.
engine = create_engine(DATABASE_URL)

# Factory that creates new DB "sessions" (conversations) on demand, all using this engine.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class — every table-model class (User, Job, etc.) will inherit from this.
Base = declarative_base()


# FastAPI dependency: opens a session, hands it to the endpoint, closes it after — even on error.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()