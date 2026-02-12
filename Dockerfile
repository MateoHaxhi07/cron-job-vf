# VILA SALES — Background Worker
FROM python:3.9-slim

# Install Chromium + dependencies (Debian packages only, no Google Chrome)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip \
    libnss3 libxss1 libxi6 libxcursor1 libxrandr2 \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 \
    libgbm1 libgtk-3-0 libdrm2 \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set Chromium path for Selenium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/
RUN mkdir -p data

CMD ["python", "-u", "worker.py"]
