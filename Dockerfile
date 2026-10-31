# Both base images are pinned by digest, so a build is reproducible and a base image update is a reviewed
# pull request (Dependabot opens it). The digest is of the multi-architecture index: amd64 and arm64.
# Build the React frontend, always on the machine doing the build: its output is plain files that are the same for
# every architecture, so a multi-architecture build does not run Node under emulation. Only its output reaches the
# final image, so Node and node_modules are not in it. The build writes to ../northstar/web/spa, which is
# /northstar/web/spa here.
FROM --platform=$BUILDPLATFORM node:25-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS frontend
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

# The version is passed in by whoever builds the image (CI reads it from pyproject.toml), so a build made
# without it says "unknown" and not a wrong number. Declared late so a new version only rebuilds the last layers.
ARG VERSION=unknown
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/declankenny/northstar" \
      org.opencontainers.image.licenses="MIT"

USER northstar
WORKDIR /data
VOLUME /data
EXPOSE 8000

# Healthy when the sign-in page answers. It is public and does not touch the database, and Python is already
# in the image, so nothing like curl is needed. urlopen raises on any error status, which makes the check fail.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4)"]

CMD ["uvicorn", "--factory", "northstar.web.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
