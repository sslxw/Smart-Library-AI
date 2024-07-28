from pydantic import BaseModel
from typing import Optional

class BookSchema(BaseModel):
    title: str
    author_id: int
    genre: Optional[str] = None
    description: Optional[str] = None
    average_rating: Optional[int] = None
    published_year: Optional[int] = None
