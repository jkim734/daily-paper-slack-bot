import os
from pathlib import Path
from typing import List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file from the project root
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ArxivConfig(BaseModel):
    categories: List[str] = Field(default_factory=lambda: ["cs.AI", "cs.LG"])
    keywords: List[str] = Field(default_factory=list)
    max_results: int = 20
    lookback_days: int = 2


class PubmedConfig(BaseModel):
    query: str = ""
    max_results: int = 15
    lookback_days: int = 3


class JournalConfig(BaseModel):
    venues: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    max_results: int = 30
    lookback_days: int = 7


class SummarizerConfig(BaseModel):
    provider: str = "gemini"  # 'gemini' or 'openai'
    model: str = "gemini-3.6-flash"
    min_k: int = 5
    max_k: int = 10
    top_k: int = 10
    language: str = "ko"
    research_interest: str = ""


class SlackConfig(BaseModel):
    bot_name: str = "Paper Briefing Bot 📚"
    bot_icon_emoji: str = ":newspaper:"
    header_title: str = "오늘의 연구 논문 브리핑"


class NotionConfig(BaseModel):
    enabled: bool = True
    database_id: Optional[str] = None
    default_status: str = "시작 전"


class StorageConfig(BaseModel):
    db_path: str = "data/history.db"


class AppConfig(BaseModel):
    sources: List[str] = Field(default_factory=lambda: ["arxiv", "journals"])
    arxiv: ArxivConfig = Field(default_factory=ArxivConfig)
    pubmed: PubmedConfig = Field(default_factory=PubmedConfig)
    journals: JournalConfig = Field(default_factory=JournalConfig)
    summarizer: SummarizerConfig = Field(default_factory=SummarizerConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    notion: NotionConfig = Field(default_factory=NotionConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    # Secrets from environment variables
    slack_webhook_url: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    notion_api_key: Optional[str] = None


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Loads configuration from YAML file and merges with environment variables."""
    if config_path is None:
        path = PROJECT_ROOT / "config.yaml"
    else:
        path = Path(config_path)

    raw_data = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

    config = AppConfig(**raw_data)

    # Inject environment secrets
    config.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    config.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    config.openai_api_key = os.getenv("OPENAI_API_KEY", "")
    config.notion_api_key = os.getenv("NOTION_API_KEY", "")
    env_notion_db = os.getenv("NOTION_DATABASE_ID", "")
    if env_notion_db:
        config.notion.database_id = env_notion_db

    # Ensure db path absolute resolution relative to project root
    if not os.path.isabs(config.storage.db_path):
        config.storage.db_path = str(PROJECT_ROOT / config.storage.db_path)

    return config
