import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-for-dev')

    # PostgreSQL URI format: postgresql+psycopg2://user:password@host:port/database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql+psycopg2://neondb_owner:npg_Fvgqc5RuV9dz@ep-old-scene-acet6c4q-pooler.sa-east-1.aws.neon.tech/mch-pacs?sslmode=require'
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOADCARE_PUBLIC_KEY = os.environ.get('UPLOADCARE_PUBLIC_KEY', 'dummy_key')
    UPLOADCARE_SECRET_KEY = os.environ.get('UPLOADCARE_SECRET_KEY', 'dummy_secret')

    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads', 'scans')


