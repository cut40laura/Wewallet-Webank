FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN if [ -f /app/deploy/hermes-agent-requirements.txt ]; then \
      python -m pip install --no-cache-dir --default-timeout=120 \
        -i "$PIP_INDEX_URL" \
        -r /app/deploy/hermes-agent-requirements.txt; \
    fi

RUN mkdir -p /data/app_data /data/ui_data /data/backups

EXPOSE 8787

CMD ["python", "ui/server.py"]
