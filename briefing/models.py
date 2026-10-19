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
    fetch_status: str = "not_requested"
    collected_at: str = ""

    def evidence(self):
        return "\n".join([self.title, self.excerpt, self.body])


class Pick(BaseModel):
    article_id: str
    country: Country
    country_reason: str


class Plan(BaseModel):
    picks: list[Pick] = Field(description="Within the configured per-country limit; unique events")
    fetch_ids: list[str] = Field(description="At most 3 picked articles needing more evidence")


class Story(BaseModel):
    article_id: str
    country: Country
    headline: str
    summary: str
    why_it_matters: str
    evidence_quote: str = Field(description="Short verbatim substring from supplied article evidence")
    update_reason: str = ""
    update_quote: str = ""
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
    selection_reason: str
    metrics: dict
    revisions: int
    warnings: list[str]
