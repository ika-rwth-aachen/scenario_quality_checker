FROM python:3.11-slim

# Agg keeps matplotlib usable without a display. The package also sets this
# itself, but declaring it here documents the requirement for the image.
ENV MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY quality_checker ./quality_checker
COPY assets ./assets
COPY example_files ./example_files

RUN pip install ".[web]"

EXPOSE 8001

CMD ["python", "-m", "quality_checker.webapp.server"]
