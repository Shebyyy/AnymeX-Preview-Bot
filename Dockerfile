FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY moderation.py .
COPY hi_trigger.py .

EXPOSE 8080

CMD ["python", "bot.py"]
