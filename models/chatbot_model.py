from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class MatchedSection(BaseModel):
    heading: str
    category: str
    score: float


class AskResponse(BaseModel):
    answer: str
    matched_sections: list[MatchedSection]
    confidence: float
    grounded: bool
