FROM python:3.11-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=180

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Increase pip resilience for slow/unstable links during image builds.
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --retries 10 --timeout 180 -r requirements.txt

COPY ./Blueprints ./Blueprints
COPY models ./models
COPY dicom_utils ./dicom_utils
COPY templates ./templates
COPY static ./static
COPY app.py .
COPY config.py .

EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0"]
