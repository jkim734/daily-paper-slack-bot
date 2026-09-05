from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Paper(BaseModel):
    id: str
    title: str
    authors: List[str] = Field(default_factory=list)
    abstract: str
    published: datetime
    url: str
    pdf_url: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    source: str = "arxiv"
    venue: Optional[str] = None
    scites: Optional[int] = None
    scirate_url: Optional[str] = None

    def clean_title(self) -> str:
        return " ".join(self.title.replace("\n", " ").split())

    def clean_abstract(self) -> str:
        return " ".join(self.abstract.replace("\n", " ").split())


class BaseFetcher(ABC):
    @abstractmethod
    def fetch_recent_papers(self, lookback_days: int = 2) -> List[Paper]:
        pass
