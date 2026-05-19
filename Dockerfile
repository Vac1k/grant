FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN pip install "poetry>=2.0,<3.0" \
    && poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

COPY . .

RUN pip install --no-deps -e .

CMD ["uvicorn", "grant_tool.main:app", "--host", "0.0.0.0", "--port", "8000"]
