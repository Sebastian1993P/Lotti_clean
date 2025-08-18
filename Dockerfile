FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./app.py
COPY templates ./templates
COPY static ./static
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["gunicorn","-w","2","-k","gthread","--threads","8","-b","0.0.0.0:8000","app:application"]
