# V4.2 Docker hotfix: pin the Debian generation and make APT resilient/configurable.
ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_BASE_IMAGE}

ARG APT_MIRROR=""
ARG APT_SECURITY_MIRROR=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Python wheels used by V4.2 do not require build-essential in the runtime image.
# APT_MIRROR/APT_SECURITY_MIRROR are optional. Example for mainland China:
#   APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
#   APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
RUN set -eux; \
    printf '%s\n' \
      'Acquire::Retries "5";' \
      'Acquire::http::Timeout "30";' \
      'Acquire::https::Timeout "30";' \
      > /etc/apt/apt.conf.d/80-enertri-network; \
    if [ -n "${APT_MIRROR}" ]; then \
      sed -ri "s#https?://deb.debian.org/debian#${APT_MIRROR%/}#g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -n "${APT_SECURITY_MIRROR}" ]; then \
      sed -ri "s#https?://deb.debian.org/debian-security#${APT_SECURITY_MIRROR%/}#g; s#https?://security.debian.org/debian-security#${APT_SECURITY_MIRROR%/}#g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
      libmagic1 \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-eng; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --prefer-binary -r requirements.txt

COPY . .
RUN chmod +x /app/entrypoint.sh /app/run_dev.sh /app/scripts/migrate.py /app/scripts/bootstrap.py /app/scripts/task_worker.py \
    && mkdir -p /app/media/videos /app/media/files /app/media/artifacts /app/media/workspace

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "app.main:app"]
