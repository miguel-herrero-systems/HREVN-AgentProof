FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY assets ./assets

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "hrevn_managed_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
