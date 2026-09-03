# Pinned by digest so a rebuild cannot silently pick up a different base image.
# Update deliberately: docker pull python:3.11-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim
FROM python:3.11-slim@sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7

ARG SCENARIO_QUALITY_CHECKER_BASE_PATH=""

# Agg keeps matplotlib usable without a display. The package also sets this
# itself, but declaring it here documents the requirement for the image.
ENV MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    SCENARIO_QUALITY_CHECKER_BASE_PATH=${SCENARIO_QUALITY_CHECKER_BASE_PATH}

WORKDIR /app

# uv installs from the committed lockfile, so the image contains the versions
# this repository was tested against rather than whatever PyPI serves today.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY quality_checker ./quality_checker

RUN uv sync --frozen --extra web --no-dev \
    && uv pip install --no-deps .

ENV PATH="/app/.venv/bin:$PATH"

# The application only ever writes under the system temp directory, so it has
# no reason to run as uid 0: a parser bug in any XML or plotting dependency
# would otherwise execute as root.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin checker \
    && chown -R checker:checker /app
USER checker

ENV HOME=/tmp/scenario-quality-checker

EXPOSE 8001

CMD ["python", "-m", "quality_checker.webapp.server"]
