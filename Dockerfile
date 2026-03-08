FROM python:3.9-slim
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-ara poppler-utils tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
