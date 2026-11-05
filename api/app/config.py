from functools import lru_cache
from urllib.parse import quote

from psycopg.conninfo import make_conninfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str
    db_user: str = "app_user"
    db_password: str
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_user: str = "survey_app"
    rabbitmq_password: str
    pepper_secret: str
    session_ttl_seconds: int = 28800
    reset_ttl_seconds: int = 900
    cookie_secure: bool = False
    app_internal_secret: str

    @property
    def database_url(self) -> str:
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )

    @property
    def rabbitmq_url(self) -> str:
        username = quote(self.rabbitmq_user, safe="")
        password = quote(self.rabbitmq_password, safe="")
        return f"amqp://{username}:{password}@rabbitmq:5672/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
