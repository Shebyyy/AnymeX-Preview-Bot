FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY moderation.py .
COPY hi_trigger.py .
COPY ai_trigger.py .
COPY source_trigger.py .
COPY trap_trigger.py .
COPY faq_trigger.py .
COPY rules_trigger.py .
COPY desk_sync.py .

EXPOSE 8080

CMD ["python", "bot.py"]
