FROM python:3.12-slim

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget gnupg build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Chrome для Selenium
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    python-telegram-bot==20.7 \
    requests==2.31.0 \
    beautifulsoup4==4.12.2 \
    selenium==4.15.0 \
    webdriver-manager==4.0.1 \
    lxml==4.9.3 \
    aiohttp==3.9.1

# Создание рабочей директории
WORKDIR /app

# Копирование ВСЕХ файлов проекта
COPY . .

# Проверка что файл существует
RUN ls -la /app/main.py

# Запуск
CMD ["python", "app/main.py"]
