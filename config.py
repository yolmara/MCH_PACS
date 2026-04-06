import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    # PostgreSQL URI format: postgresql+psycopg2://user:password@host:port/database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql+psycopg2://postgres:postgres@db:5432/pacsdb'
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

    MAX_CONTENT_LENGTH = 8 * 1024 * 1024 * 1024

    # External OHIF entrypoint used for dashboard/viewer redirects
    OHIF_VIEWER_URL = os.environ.get("OHIF_VIEWER_URL", "http://localhost:8080").rstrip("/")

    # Orthanc ingestion settings
    ORTHANC_API_URL = os.environ.get("ORTHANC_API_URL", "http://orthanc:8042").rstrip("/")
    ORTHANC_ADMIN_USERNAME = os.environ.get("ORTHANC_ADMIN_USERNAME", "admin")
    ORTHANC_ADMIN_PASSWORD = os.environ.get("ORTHANC_ADMIN_PASSWORD", "")
    ORTHANC_INGEST_ENABLED = os.environ.get("ORTHANC_INGEST_ENABLED", "1").strip().lower() in {"1", "true", "yes", "y"}
