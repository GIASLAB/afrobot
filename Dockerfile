FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY news_bot.py news_sources.py article.py rescript.py picker.py virality.py ./

# Long-running poller, not a web service. No port is exposed.
CMD ["python", "news_bot.py"]
