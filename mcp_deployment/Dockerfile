FROM python:3.12-slim
LABEL authors='shyin.lim'

RUN apt-get update && apt-get install -y git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Taipei

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# Create non-root user matching host GitLab runner UID/GID
# Use --non-unique to avoid conflict if GID/UID 998 is already taken by the base image
RUN groupadd --non-unique -g 998 gitlab-runner \
    && useradd --non-unique -u 998 -g 998 -m gitlab-runner \
    && chown -R gitlab-runner:gitlab-runner /app
