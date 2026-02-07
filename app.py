from flask import Flask, render_template
from config import Config
from models import db
from flask_migrate import Migrate
import time
from sqlalchemy.exc import OperationalError


# ----------------------------------------------------
#  APPLICATION FACTORY
# ----------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    app.config['SESSION_TYPE'] = 'filesystem'

    # Initialize database + migrations
    db.init_app(app)
    
    # Retry database connection
    with app.app_context():
        retries = 5
        for attempt in range(retries):
            try:
                db.create_all()
                print("✅ Database connected successfully")
                break
            except OperationalError as e:
                if attempt < retries - 1:
                    print(f"⚠️ Database connection attempt {attempt + 1} failed. Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    print(f"❌ Failed to connect to database after {retries} attempts: {e}")
                    raise
    
    Migrate(app, db)
    
    @app.after_request
    def disable_caching(response):
       response.headers["Cache-Control"] = "no-cache"
       return response

    # Register Jinja filters
    register_filters(app)

    # Register Blueprints
    register_blueprints(app)

    return app


# ----------------------------------------------------
#  BLUEPRINT REGISTRATION
# ----------------------------------------------------
def register_blueprints(app):
    from Blueprints.upload.routes import upload_bp
    from Blueprints.dicom.routes import dicom_bp
    from Blueprints.dashboard.routes import home_bp
    from Blueprints.dicomweb.routes import dicomweb_bp
    from Blueprints.dicomweb.wado import wado_bp
    from Blueprints.dicomweb.stow import stow_bp
    from Blueprints.ohif_viewer.routes import pacs_bp
    from Blueprints.wards.routes import wards_bp
    from Blueprints.auth.routes import auth_bp
    from Blueprints.ris.routes import ris_bp

    app.register_blueprint(home_bp, url_prefix="/")
    app.register_blueprint(upload_bp, url_prefix="/upload")
    app.register_blueprint(dicom_bp, url_prefix="/dicom")
    app.register_blueprint(pacs_bp, url_prefix="/ohif")
    app.register_blueprint(wards_bp, url_prefix="/wards")
    app.register_blueprint(auth_bp)
    app.register_blueprint(ris_bp, url_prefix='/ris')
    
    # DICOMWeb endpoints - all under /dicomweb
    app.register_blueprint(dicomweb_bp, url_prefix='/dicomweb')  
    app.register_blueprint(wado_bp, url_prefix='/dicomweb')      
    app.register_blueprint(stow_bp, url_prefix='/dicomweb')      


# ----------------------------------------------------
#  JINJA FILTERS
# ----------------------------------------------------
def register_filters(app):
    from pytz import timezone, utc

    @app.template_filter("cat_time")
    def cat_time_filter(utc_dt, fmt='%Y-%m-%d %H:%M:%S'):
        if utc_dt is None:
            return ''
        cat = timezone('Africa/Harare')
        local_dt = utc_dt.replace(tzinfo=utc).astimezone(cat)
        return local_dt.strftime(fmt)


# ----------------------------------------------------
#  RUN APP
# ----------------------------------------------------
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)  # ✅ FIXED: dots not commas!
    
    
