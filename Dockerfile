# 단일 서비스 이미지: React 빌드 결과를 FastAPI가 함께 제공한다 (docs/design.md "배포").

# ---- 1단계: 프런트 빌드 ----
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2단계: 서버 ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# 의존성은 소스보다 먼저 설치해서 소스만 바뀌면 이 층을 다시 쓴다
RUN pip install --no-cache-dir uv==0.13.7
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
# 데이터 파일은 이미지에 읽기 전용으로 담는다 (서버는 파일을 쓰지 않는다)
COPY profiles ./profiles
COPY examples ./examples
COPY datasources ./datasources
COPY semantic ./semantic
COPY --from=frontend /frontend/dist ./frontend/dist

RUN useradd --create-home --uid 10001 app
USER app

# 배포 환경이 주는 PORT에 0.0.0.0으로 붙는다 (없으면 8085)
CMD ["sh", "-c", "exec uvicorn text2sql.main:app --host 0.0.0.0 --port ${PORT:-8085}"]
