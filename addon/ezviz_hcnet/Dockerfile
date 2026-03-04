FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ezviz

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY service /opt/ezviz/service
COPY lib/arm64 /opt/ezviz/lib/arm64

ENV EZVIZ_SDK_LIB_DIR=/opt/ezviz/lib/arm64

EXPOSE 8099

CMD ["python3", "-m", "uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8099"]
