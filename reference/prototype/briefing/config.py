import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    timezone: str = "Europe/London"
    hour: int = 8
    minute: int = 0
    recipient: str = "yumi.heo.01@gmail.com"
    transport: str = "resend"
    sender: str = "Yumi IT Briefing <onboarding@resend.dev>"
    model: str = "gpt-4.1-mini"

    @classmethod
    def load(cls):
        load_dotenv(ROOT / ".env")
        result = cls(
            data_dir=Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve(),
            timezone=os.getenv("BRIEFING_TIMEZONE", "Europe/London"),
            hour=int(os.getenv("BRIEFING_HOUR", "8")),
            minute=int(os.getenv("BRIEFING_MINUTE", "0")),
            recipient=os.getenv("MAIL_TO", "yumi.heo.01@gmail.com"),
            transport=os.getenv("MAIL_TRANSPORT", "resend"),
            sender=os.getenv("MAIL_FROM", "Yumi IT Briefing <onboarding@resend.dev>"),
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        )
        ZoneInfo(result.timezone)
        if not 0 <= result.hour <= 23 or not 0 <= result.minute <= 59:
            raise ValueError("Invalid briefing time")
        if result.recipient != "yumi.heo.01@gmail.com":
            raise ValueError("This private project is restricted to Yumi's configured address")
        if result.transport not in {"resend", "smtp"}:
            raise ValueError("MAIL_TRANSPORT must be resend or smtp")
        return result

    def missing(self, *, send=False):
        names = ["OPENAI_API_KEY"]
        if os.getenv("LANGSMITH_TRACING", "false").lower() == "true":
            names.append("LANGSMITH_API_KEY")
        if send:
            names.extend(["RESEND_API_KEY"] if self.transport == "resend" else
                         ["SMTP_USER", "SMTP_PASSWORD"])
        return [name for name in names if not os.getenv(name)]
