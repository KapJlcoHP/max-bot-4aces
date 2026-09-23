import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database/app.db")
engine = create_engine(DATABASE_URL)
session = sessionmaker(bind=engine)
