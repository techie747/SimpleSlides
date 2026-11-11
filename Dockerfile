FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY walkthru walkthru
COPY web web
ENV WALKTHRU_DATA_DIR=/data
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "walkthru.app:app", "--host", "0.0.0.0", "--port", "8000"]
