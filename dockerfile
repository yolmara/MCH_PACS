FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
# With
COPY ./Blueprints ./Blueprints
COPY app.py .
COPY config.py .
COPY requirements.txt .
COPY models ./models
COPY dicom_utils ./dicom_utils
COPY templates ./templates
COPY static ./static
COPY app.py .
EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0"]
