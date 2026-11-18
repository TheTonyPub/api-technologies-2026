from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://spark:spark@postgres:5432/spark"
    ml_model_addr: str = "ml-model:50051"
    # gateway ждёт нижние сервисы 0.9 с, так что модель должна успеть раньше (иначе gateway обрежет запрос сам)
    ml_timeout_sec: float = 0.6
    # от какой даты считаем возраст компании, today (дата запроса) или data_as_of (дата среза)
    scoring_as_of: str = "today"


settings = Settings()
