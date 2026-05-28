FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watch_obsidian.py .

CMD ["python", "watch_obsidian.py"]
