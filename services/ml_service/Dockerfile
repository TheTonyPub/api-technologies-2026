FROM python:3.12-slim

WORKDIR /app

COPY services/ml_service/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY services ./services

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8001 50051

CMD ["uvicorn", "services.ml_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
