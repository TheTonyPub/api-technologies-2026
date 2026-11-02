FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mocks ./mocks
RUN useradd --system --uid 10001 mock && mkdir -p /data && chown mock /data
USER mock
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# MOCK_MODULE задаётся в docker-compose: abs | client_data | spark | monitoring | notify
CMD ["sh", "-c", "exec uvicorn mocks.${MOCK_MODULE}.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
