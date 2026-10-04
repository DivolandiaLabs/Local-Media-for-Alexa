# Imagen multi-arquitectura (arm64 / armv7 / amd64):
#   docker build -t localmedia .
#   docker run -d --name localmedia --restart unless-stopped \
#     -p 8080:8080 -p 8765:8765 -v localmedia-data:/data -v /media/musica:/music:ro localmedia
# Luego añade /music como carpeta en la web.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY localmedia ./localmedia
ENV LOCALMEDIA_DATA=/data
VOLUME ["/data"]
EXPOSE 8080 8765
CMD ["python", "-m", "localmedia"]
