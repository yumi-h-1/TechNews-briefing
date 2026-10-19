from datetime import datetime, timezone

from briefing.models import Article, Draft, Story


def demo_content():
    """Invented content, deliberately marked as a demo; never passed to the mailer."""
    articles, stories = [], []
    examples = [
        ("UK", "en", "Demo: a UK research team shares an AI evaluation toolkit",
         "This fictional example shows how a UK story will appear. It is not a real news report.",
         "The briefing will explain the practical significance using the linked source."),
        ("US", "en", "Demo: a US software company announces a security update",
         "This fictional example demonstrates the English US section. No actual product announcement is being reported.",
         "Real issues will include supported details and a link to the original report."),
        ("KR", "ko", "예시: 국내 연구진의 AI 기술 발표",
         "한국 섹션의 표시 방식을 보여주는 가상 기사입니다. 실제 뉴스가 아니며, 운영 시에는 한국어 주요 언론사의 보도를 요약합니다.",
         "원문을 근거로 기술의 의미와 국내 영향을 간결하게 설명합니다."),
    ]
    for country, language, title, summary, why in examples:
        article = Article(id=country, title=title, url="https://example.invalid/demo/" + country,
                          source="가상 언론사 · DEMO", language=language,
                          published=datetime.now(timezone.utc).isoformat(), excerpt=summary)
        articles.append(article)
        stories.append(Story(article_id=country, country=country, headline=title, summary=summary,
                             why_it_matters=why, evidence_quote=summary[:30], event_key="demo-" + country.lower()))
    return Draft(stories=stories), articles
