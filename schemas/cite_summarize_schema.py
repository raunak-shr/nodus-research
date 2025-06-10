from pydantic import BaseModel
from schemas.search_schema import ExtractionResult


class CitationInput(BaseModel):
    extraction_response: ExtractionResult

class SummarizerInput(BaseModel):
    clean_extracts: ExtractionResult