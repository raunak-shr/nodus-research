from pydantic import BaseModel
from typing_extensions import TypedDict, List


class ExtractionItem(BaseModel):
    title: str
    url: str
    raw_content: str
    images: List[str]
    score: float


class ExtractionResult(BaseModel):
    results: List[ExtractionItem]


class SearchItem(BaseModel):
    results: List[ExtractionItem]


class SearchResult(BaseModel):
    query: str
    follow_up_questions: None | List[str]
    answer: None | str
    images: List
    results: List[SearchItem]
    response_time: float
