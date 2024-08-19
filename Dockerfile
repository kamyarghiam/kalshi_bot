
# This docker file is used to run the project in a container. Run this from the root directory:
# docker build -t debug .
# docker run -it --entrypoint sh --mount type=bind,source="$(pwd)"/local/coledb_storage,target=/app/local/coledb_storage debug

FROM python:3.11-slim
WORKDIR /app
RUN pip install poetry

COPY pyproject.toml poetry.lock /app/
RUN apt-get update && apt-get install -y gcc python3-dev
RUN poetry install --no-root
COPY . /app/