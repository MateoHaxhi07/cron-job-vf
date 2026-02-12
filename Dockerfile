# VILA SALES — Background Worker
FROM python:3.9-slim

# Install Chrome dependencies
RUN apt-get update && apt-get install -y \
    wget gnupg curl unzip \
    libnss3 libgconf-2-4 libxi6 libxcursor1 libxrandr2 \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google.list && \
    apt-get update && apt-get install -y google-chrome-stable && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/
RUN mkdir -p data

# Run as a long-lived worker (NOT a one-shot cron job)
CMD ["python", "-u", "worker.py"]
