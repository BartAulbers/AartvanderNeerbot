FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY bot/ ./bot/

# Directory for persistent data, browser storage & debug screenshots
RUN mkdir -p /app/data

CMD ["python", "-m", "bot.main"]
