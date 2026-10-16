from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Country = Literal["UK", "US", "KR"]


class Article(BaseModel):
    id: str
    title: str
    url: str
    source: str
    language: str
    published: str
    excerpt: str
    body: str = ""

    def evidence(self):
        return "\n".join([self.title, self.excerpt, self.body])


class Pick(BaseModel):
    article_id: str
    country: Country
    country_reason: str


class Plan(BaseModel):
    picks: list[Pick] = Field(description="At most 3 per country, 9 total; unique events")
    fetch_ids: list[str] = Field(description="At most 3 picked articles needing more evidence")


class Story(BaseModel):
    article_id: str
    country: Country
    headline: str
    summary: str
    why_it_matters: str
    evidence_quote: str = Field(description="Short verbatim substring from supplied article evidence")
    event_key: str = Field(description="Stable lowercase English slug for the underlying event")


class Draft(BaseModel):
    stories: list[Story]


class Review(BaseModel):
    approved_ids: list[str] = Field(description="Only stories fully supported by source evidence")
    feedback: list[str] = Field(description="Specific problems to fix; empty if all pass")


class AgentState(TypedDict, total=False):
    articles: list[dict]
    history: list[dict]
    plan: dict
    draft: dict
    approved: list[str]
    feedback: list[str]
    revisions: int
    warnings: list[str]
