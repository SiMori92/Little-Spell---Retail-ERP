# Deploy image for Railway.
#
# A Dockerfile rather than Nixpacks auto-detection: the build is then the same
# locally, in CI and on Railway, and a uv project's build steps are explicit rather
# than inferred.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependencies first, so a code change does not reinstall the world.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Build the WhiteNoise manifest at image build time. These two variables are needed
# only so settings.py imports; nothing connects to a database here, and neither
# value reaches the running container.
RUN DJANGO_SECRET_KEY=build-time-only-not-a-real-key \
    DATABASE_URL=postgresql://build@localhost:5432/build \
    DJANGO_DEBUG=0 \
    uv run python manage.py collectstatic --noinput

CMD ["sh", "-c", "uv run gunicorn config.wsgi --bind 0.0.0.0:$PORT"]
