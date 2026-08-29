FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY trading_system ./trading_system
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "trading_system.worker"]

