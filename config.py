import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-for-dev')

    # PostgreSQL URI format: postgresql+psycopg2://user:password@host:port/database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
    'postgresql+psycopg2://coder911:coder.03@db:5432/pacsdb'
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')


