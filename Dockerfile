FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NORTHSTAR_DB=/data/northstar.db

# Install from a throwaway copy so the app runs from site-packages, the way it would
# anywhere else. A missing package-data entry then fails here instead of hiding.
COPY pyproject.toml /build/pyproject.toml
COPY northstar /build/northstar
RUN pip install /build && rm -rf /build

RUN useradd --system --uid 1000 --no-create-home northstar \
    && mkdir /data && chown northstar:northstar /data

USER northstar
WORKDIR /data
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "--factory", "northstar.web.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
