FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ANONYMIZED_TELEMETRY=False PORT=8501

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY nanopore_triage ./nanopore_triage
COPY data ./data
COPY app.py ./

RUN useradd -m triage && chown -R triage /app
USER triage

# Bake the embedding model (into ~triage/.cache) and the seeded Chroma index into
# the image so the first request doesn't download anything.
RUN python -m nanopore_triage.cli seed

EXPOSE 8501
CMD streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true
