import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-for-dev')
    
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///mch_pacs.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOADCARE_PUBLIC_KEY = os.environ.get('UPLOADCARE_PUBLIC_KEY')
    UPLOADCARE_SECRET_KEY = os.environ.get('UPLOADCARE_SECRET_KEY')

    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads', 'scans')


