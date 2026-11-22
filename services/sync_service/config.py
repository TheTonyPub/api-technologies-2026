"""Настройки сервиса. Всё берём из переменных окружения (их задаёт docker compose из .env)."""
import os

# --- внешние API (моки) ---
BASE_URL = os.getenv("EXTERNAL_BASE_URL", "https://api.external-services.dataprosvet.ru").rstrip("/")
API_KEY = os.getenv("API_KEY", "")  # ключ команды, лежит только в .env
MOCK_SCENARIO = os.getenv("MOCK_SCENARIO", "")  # slow / timeout / error / unavailable / ratelimit

REQUEST_TIMEOUT = 10  # секунд на один запрос, дольше ждать не будем
MAX_RETRIES = 4  # сколько раз пробуем один запрос при 429 / 503 / таймауте
MAX_RPS = 15  # у моков лимит 20 запросов/с, берём с запасом

# --- хранилища ---
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "antifraud")
POSTGRES_USER = os.getenv("POSTGRES_USER", "antifraud")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "antifraud")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# --- что и как часто обновляем ---
TX_DAYS = 30  # операции храним за последние 30 дней
TX_OVERLAP_HOURS = 1  # при обновлении берём чуть больше, дубли отсекает ON CONFLICT
CLIENTS_EVERY = int(os.getenv("CLIENTS_EVERY_MINUTES", "60")) * 60
TX_EVERY = int(os.getenv("TX_EVERY_MINUTES", "5")) * 60
PROFILES_EVERY = int(os.getenv("PROFILES_EVERY_MINUTES", "360")) * 60
RISKS_EVERY = int(os.getenv("RISKS_EVERY_MINUTES", "360")) * 60
RETRY_FAILED_AFTER = 60  # если загрузка упала, пробуем снова через минуту

HTTP_PORT = 8000  # /health и /stats
