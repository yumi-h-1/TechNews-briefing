from html import escape

from briefing.models import Article, Draft


def render_digest(draft, articles, day, warnings=(), demo=False):
    by_id = {a.id: a for a in articles}
    label = "[DEMO · 가상 데이터] " if demo else ""
    subject = f"{label}IT & AI Briefing · {day} · UK / US / 한국"
    text = [subject, ""]
    cards = []
    for country, title, empty in [
        ("UK", "United Kingdom", "No qualifying new stories were selected. Coverage may be limited; see notes below."),
        ("US", "United States", "No qualifying new stories were selected. Coverage may be limited; see notes below."),
        ("KR", "대한민국", "선정된 새 기사가 없습니다. 수집 범위가 제한됐을 수 있으니 아래 안내를 확인해 주세요."),
    ]:
        stories = [s for s in draft.stories if s.country == country]
        text.extend([title, "─" * 24])
        content = []
        for story in stories:
            article = by_id[story.article_id]
            why = "왜 중요한가" if country == "KR" else "Why it matters"
            note = "RSS 제공 내용 기반" if country == "KR" else "Based on RSS-provided evidence"
            if article.body:
                note = "RSS 및 접근 가능한 본문 기반" if country == "KR" else "Based on RSS and accessible article text"
            text.extend([story.headline, story.summary, f"{why}: {story.why_it_matters}",
                         f"{article.source} · {article.published[:16]} UTC · {note}", article.url, ""])
            content.append(f'''<article style="padding:18px 0;border-bottom:1px solid #e3e8ef">
<h3 style="margin:0 0 10px;font-size:18px;line-height:1.45"><a style="color:#152c4d;text-decoration:none" href="{escape(article.url, quote=True)}">{escape(story.headline)}</a></h3>
<p style="margin:0 0 10px;line-height:1.7">{escape(story.summary)}</p>
<p style="margin:0 0 12px;line-height:1.7;color:#40516a"><b>{why}:</b> {escape(story.why_it_matters)}</p>
<p style="font-size:12px;line-height:1.5;color:#65758b;margin:0">{escape(article.source)} · {escape(article.published[:16])} UTC<br>{note} · <a href="{escape(article.url, quote=True)}">원문 / Read source</a></p></article>''')
        if not stories:
            text.extend([empty, ""])
            content.append(f'<p style="color:#65758b;line-height:1.7">{empty}</p>')
        lang = "ko" if country == "KR" else "en"
        cards.append(f'<section lang="{lang}" style="margin-top:32px"><h2 style="font-size:21px;border-bottom:3px solid #2563eb;padding-bottom:10px">{title}</h2>{"".join(content)}</section>')
    notes = list(dict.fromkeys(warnings))
    if demo:
        notes.insert(0, "가상 기사로 구성한 화면 예시입니다. 실제 뉴스가 아닙니다.")
    notes.append("AI-generated summaries may contain errors. Read linked sources for details. / AI 요약은 원문과 함께 확인해 주세요.")
    text.extend(["Notes / 안내", *notes])
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;background:#eef2f7;font-family:Arial,'Apple SD Gothic Neo',sans-serif;color:#1c2b40">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="640" style="width:100%;max-width:640px;background:#fff;border-radius:12px" cellspacing="0" cellpadding="0"><tr><td style="padding:32px">
<p style="font-size:12px;letter-spacing:2px;color:#2563eb;margin:0 0 10px">YUMI'S MORNING BRIEFING</p>
<h1 style="font-size:30px;line-height:1.3;margin:0 0 12px">{label}IT &amp; AI</h1>
<p style="color:#65758b;margin:0">{escape(day)} · 08:00 Europe/London<br>United Kingdom · United States · 대한민국</p>
{"".join(cards)}
<div style="margin-top:30px;padding-top:18px;border-top:1px solid #e3e8ef;font-size:12px;color:#65758b;line-height:1.7">{"".join(f"<p>{escape(n)}</p>" for n in notes)}</div>
</td></tr></table></td></tr></table></body></html>'''
    return {"subject": subject, "text": "\n".join(text), "html": html}
