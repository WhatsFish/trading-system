FROM python:3.12-slim
WORKDIR /app
COPY research/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/trading_system ./trading_system
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "trading_system.reference_worker"]
