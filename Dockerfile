# Imagen multi-arquitectura (arm64 / armv7 / amd64):
#   docker build -t pimedia .
#   docker run -d --name pimedia --restart unless-stopped \
#     -p 8080:8080 -p 8765:8765 -v pimedia-data:/data -v /media/musica:/music:ro pimedia
# Luego añade /music como carpeta en la web.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pimedia ./pimedia
ENV PIMEDIA_DATA=/data
VOLUME ["/data"]
EXPOSE 8080 8765
CMD ["python", "-m", "pimedia"]
