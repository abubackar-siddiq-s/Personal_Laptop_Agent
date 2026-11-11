from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
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
    # Rate Limit & Intelligent Provider Fallback
    auto_provider_fallback:bool=False
    fallback_provider:str="gemini"
    fallback_model:str="gemini-2.5-flash"
    max_rate_limit_retries:int=2
    max_history_turns:int=6
    max_context_tokens_groq:int=3200
    model_config=SettingsConfigDict(env_file=BASE/".env",extra="ignore")
settings=Settings()
