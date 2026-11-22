FROM python:3.12-slim

WORKDIR /app

# Копируем зависимости
COPY services/decision_service/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект (чтобы были доступны proto-файлы и модули)
COPY services ./services

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 50052

# Запускаем сервер
CMD ["python", "-m", "services.decision_service.server"]
