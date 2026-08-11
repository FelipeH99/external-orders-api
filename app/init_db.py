from app.database import Base, SessionLocal, engine
from app.services import seed_products


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_products(db)
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
