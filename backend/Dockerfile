FROM python:3.10-slim

WORKDIR /app

# Install system packages for headless Chrome
RUN apt-get update && apt-get install -y \
    libnss3 libxss1 libasound2 libx11-6 libx11-xcb1 \
    libxcomposite1 libxcursor1 libxdamage1 libxi6 libxtst6 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
    libxrandr2 libgbm1 libgtk-3-0 libdrm2 xvfb \
    wget unzip curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy all source files
COPY app.py .
COPY requirements.txt .
COPY chromium/ ./chromium/
RUN mkdir -p /app/tmp

# Make sure Chrome binaries are executable
RUN chmod +x /app/chromium/chrome-linux64/chrome
RUN chmod +x /app/chromium/chromedriver
RUN chmod +x /app/chromium/chrome-linux64/chrome_crashpad_handler || true

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "app.py"]