from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.orm import declarative_base
import enum
import datetime

Base = declarative_base()

class PostType(enum.Enum):
    rent = "rent"
    sell = "sell"


class Post(Base):
    __tablename__ = "posts"

    channel_id = Column(String, primary_key=True)
    source_id = Column(Integer, primary_key=True)  # Telegram message.id

    type = Column(Enum(PostType), nullable=False)

    district = Column(String, nullable=True)
    metro = Column(String, nullable=True)
    address = Column(String, nullable=True)

    rooms = Column(Integer, nullable=True)
    size_sqm = Column(Integer, nullable=True)
    floor = Column(String, nullable=True)

    price = Column(Integer, nullable=True)
    pets = Column(String, nullable=True)
    tenants = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    deleted = Column(Boolean, default=False)

    def __repr__(self):
        return f"<Post {self.type} {self.district} {self.price}$ (id={self.channel_id}:{self.source_id})>"