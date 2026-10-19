import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPIENT = "yumi.heo.01@gmail.com"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("var")
    timezone: str = "Europe/London"
    recipient: str = RECIPIENT
    sender: str = ""
    model: str = "gpt-4.1-mini"
    preparation_minutes: int = 30
    max_per_country: int = 3

    def __post_init__(self):
        if self.recipient != RECIPIENT or self.timezone != "Europe/London":
            raise ValueError("Single recipient and Europe/London are fixed requirements")
        if not 1 <= self.preparation_minutes <= 120:
            raise ValueError("Preparation must start 1–120 minutes before 08:00")
        if not 1 <= self.max_per_country <= 5:
            raise ValueError("MAX_PER_COUNTRY must be between 1 and 5")

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        return cls(data_dir=Path(os.getenv("DATA_DIR", "var")), sender=os.getenv("MAIL_FROM", ""),
                   recipient=os.getenv("MAIL_TO", RECIPIENT), model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                   preparation_minutes=int(os.getenv("PREPARATION_MINUTES", "30")),
                   max_per_country=int(os.getenv("MAX_PER_COUNTRY", "3")))

    def missing(self, *, send=False):
        names = ["OPENAI_API_KEY"]
        if os.getenv("LANGSMITH_TRACING", "false").lower() == "true":
            names.append("LANGSMITH_API_KEY")
        if send:
            names.extend(["RESEND_API_KEY", "MAIL_FROM"])
        return [name for name in names if not os.getenv(name)]
