# AutoMoto AI - hosted (multi-user) server image.
#   docker build -t automoto .
#   docker run -p 8765:8765 -v automoto-data:/data \
#     -e NVIDIA_API_KEY=... -e AUTOMOTO_ADMIN_USER=you -e AUTOMOTO_ADMIN_PASSWORD='a long password' \
#     -e AUTOMOTO_ALLOWED_HOSTS=your.domain automoto
# See docs/HOSTING.md. Build with --build-arg WITH_OFFICE=1 to add LibreOffice (PDF export; ~600 MB more).
FROM python:3.12-slim

ARG WITH_OFFICE=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    AUTOMOTO_MODE=multiuser AUTOMOTO_DATA_DIR=/data AUTOMOTO_HOST=0.0.0.0 \
    AUTOMOTO_SIGNUP=invite AUTOMOTO_DEFAULT_QUOTA_MINUTES=60 AUTOMOTO_COOKIE_SECURE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils php-cli p7zip-full ca-certificates \
 && if [ "$WITH_OFFICE" = "1" ]; then apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc libreoffice-impress; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY automoto ./automoto
RUN pip install --upgrade pip && pip install ".[office,data]" && pip uninstall -y pip setuptools 2>/dev/null || true

# never run as root; all state lives in /data (mount a volume there to keep accounts and files)
RUN useradd --create-home --uid 10001 automoto && mkdir -p /data && chown automoto:automoto /data
USER automoto
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8765\")}/api/health',timeout=4)" || exit 1
# Hosted (multi-user) by default. Single-user: -e AUTOMOTO_MODE=local -e AUTOMOTO_HOST=127.0.0.1 --network host
# (Linux; see compose.yaml). PORT is set by Render / Koyeb / Hugging Face; 8765 otherwise.
CMD ["sh", "-c", "exec python -m automoto serve --host \"${AUTOMOTO_HOST:-0.0.0.0}\" --port \"${PORT:-8765}\" --no-browser"]
