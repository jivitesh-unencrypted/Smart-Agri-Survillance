from sqlalchemy.orm import Session

from app.models.settings import AppSettings


def get_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_settings(db: Session, updates: dict) -> AppSettings:
    row = get_settings(db)
    for key, value in updates.items():
        if value is not None and hasattr(row, key):
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
