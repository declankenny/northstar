# Both base images are pinned by digest, so a build is reproducible and a base image update is a reviewed
# pull request (Dependabot opens it). The digest is of the multi-architecture index: amd64 and arm64.
# Build the React frontend. Only its output reaches the final image, so Node and node_modules
# are not in it. The build writes to ../northstar/web/spa, which is /northstar/web/spa here.
FROM node:24-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim@sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NORTHSTAR_DB=/data/northstar.db

# Install from a throwaway copy so the app runs from site-packages, the way it would
# anywhere else. A missing package-data entry then fails here instead of hiding.
COPY pyproject.toml /build/pyproject.toml
COPY northstar /build/northstar
COPY --from=frontend /northstar/web/spa /build/northstar/web/spa
RUN pip install /build && rm -rf /build

# pip is only needed to install the app. It vendors its own copies of libraries (msgpack, urllib3,
# setuptools) that the app never uses, which image scanners report with known vulnerabilities until pip
# itself ships updated copies. Removing it clears those findings and means nothing can be installed into
# a running container.
RUN pip uninstall --yes pip

RUN useradd --system --uid 1000 --no-create-home northstar \
    && mkdir /data && chown northstar:northstar /data

USER northstar
WORKDIR /data
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "--factory", "northstar.web.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
