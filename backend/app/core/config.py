from pathlib import Path
import logging
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("laptop_ai.config")
BASE = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    app_name:str="LAPTOP AI"
    host:str="127.0.0.1"
    database_path:str="data/laptop_ai.db"
    default_provider:str="groq"
    default_model:str="openai/gpt-oss-20b"
    gemini_api_key:str=""
    groq_api_key:str=""
    openrouter_api_key:str=""
    # Rate Limit & Intelligent Provider Fallback (Mandatory: Always True)
    auto_provider_fallback:bool=True
    fallback_provider:str="gemini"
    fallback_model:str="gemini-2.5-flash"
    max_rate_limit_retries:int=2
    max_history_turns:int=6
    max_context_tokens_groq:int=3200
    model_config=SettingsConfigDict(env_file=BASE/".env",extra="ignore")

    @field_validator("auto_provider_fallback", mode="before")
    @classmethod
    def enforce_mandatory_auto_fallback(cls, v):
        if v is False or (isinstance(v, str) and v.lower() in ("false", "0", "no", "off")):
            logger.warning(
                "Config warning: auto_provider_fallback cannot be disabled. "
                "Mandatory policy ensures rate-limit fallback across Gemini, Groq, and OpenRouter remains active."
            )
        return True

    def __setattr__(self, name, value):
        if name == "auto_provider_fallback" and not value:
            # Mandatory enforcement: Auto Provider Fallback on HTTP 429 cannot be disabled
            logger.warning("Attempt to set auto_provider_fallback to False ignored. Policy permanently enforces True.")
            super().__setattr__("auto_provider_fallback", True)
            return
        super().__setattr__(name, value)
settings=Settings()
