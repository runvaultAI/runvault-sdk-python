FROM python:3.13-slim

RUN useradd -m -u 1000 -s /bin/bash dev

WORKDIR /agent-sdk

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[all,dev]"

USER dev

CMD ["pytest"]
