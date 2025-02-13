# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install system dependencies (for Chrome and ChromeDriver)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    unzip \
    libnss3 \
    libgconf-2-4 \
    libxi6 \
    libxcursor1 \
    libxrandr2 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google.list && \
    apt-get update && apt-get install -y google-chrome-stable && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy your project code into the container
COPY . /app/

# Ensure the data directory exists
RUN mkdir -p data

# The command to run both scripts sequentially
CMD ["sh", "-c", "PYTHONUNBUFFERED=1 python DATA_SCRAPE.py"]

