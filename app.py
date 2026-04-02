from flask import Flask, render_template, jsonify
from config import Config
from models import db, User
from flask_migrate import Migrate
import os
import time
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix


# ----------------------------------------------------
#  APPLICATION FACTORY
# ----------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Respect reverse proxy headers (host/port/scheme) for correct URL generation.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_port=1)
    
    app.config['SESSION_TYPE'] = 'filesystem'
    # Allow large multipart folder uploads by raising parser safeguards.
    # MAX_CONTENT_LENGTH still enforces the hard request-size ceiling.
    app.config['MAX_FORM_PARTS'] = 20000
    app.config['MAX_FORM_MEMORY_SIZE'] = 16 * 1024 * 1024

    # Initialize database + migrations
    db.init_app(app)

    def ensure_bootstrap_admin():
        username = (os.environ.get("BOOTSTRAP_ADMIN_USERNAME") or "").strip()
        password = (os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
        if not username or not password:
            return

        reset = (os.environ.get("BOOTSTRAP_ADMIN_RESET") or "").strip().lower() in {"1", "true", "yes", "y"}
        full_name = (os.environ.get("BOOTSTRAP_ADMIN_FULL_NAME") or "").strip() or username
        email = (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "").strip() or None

        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(
                username=username,
                role="admin",
                full_name=full_name,
                email=email,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            print(f"✅ Bootstrapped admin user '{username}'")
        elif reset:
            user.set_password(password)
            user.role = "admin"
            user.is_active = True
            if full_name:
                user.full_name = full_name
            if email is not None:
                user.email = email
            db.session.commit()
            print(f"✅ Reset admin user '{username}'")
    
    # Retry database connection
    with app.app_context():
        retries = 5
        for attempt in range(retries):
            try:
                db.create_all()
                ensure_bootstrap_admin()
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

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(err):
        return jsonify({
            "error": "Request too large",
            "message": str(err),
            "max_content_length": app.config.get("MAX_CONTENT_LENGTH"),
            "max_form_parts": app.config.get("MAX_FORM_PARTS"),
            "max_form_memory_size": app.config.get("MAX_FORM_MEMORY_SIZE"),
        }), 413

    # Register Jinja filters/context
    register_filters(app)
    register_context_processors(app)

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
    from Blueprints.patients.routes import patients_bp

    app.register_blueprint(home_bp, url_prefix="/")
    app.register_blueprint(upload_bp, url_prefix="/upload")
    app.register_blueprint(dicom_bp, url_prefix="/dicom")
    app.register_blueprint(pacs_bp, url_prefix="/ohif")
    app.register_blueprint(wards_bp, url_prefix="/wards")
    app.register_blueprint(auth_bp)
    app.register_blueprint(ris_bp, url_prefix='/ris')
    app.register_blueprint(patients_bp, url_prefix='/patients')
    
    # DICOMWeb endpoints - all under /dicomweb
    app.register_blueprint(dicomweb_bp, url_prefix='/dicomweb')  
    app.register_blueprint(wado_bp, url_prefix='/dicomweb')      
    app.register_blueprint(stow_bp, url_prefix='/dicomweb')      


# ----------------------------------------------------
#  JINJA FILTERS
# ----------------------------------------------------
def register_filters(app):
    import re
    from html import unescape
    from pytz import timezone, utc

    @app.template_filter("cat_time")
    def cat_time_filter(utc_dt, fmt='%Y-%m-%d %H:%M:%S'):
        if utc_dt is None:
            return ''
        cat = timezone('Africa/Harare')
        if utc_dt.tzinfo is None:
            utc_dt = utc.localize(utc_dt)
        local_dt = utc_dt.astimezone(cat)
        return local_dt.strftime(fmt)

    @app.template_filter("strip_html")
    def strip_html_filter(value):
        if value is None:
            return ""
        return unescape(re.sub(r"<[^>]+>", "", str(value)))


# ----------------------------------------------------
#  JINJA CONTEXT
# ----------------------------------------------------
def register_context_processors(app):
    @app.context_processor
    def inject_ohif_base_url():
        ohif_base_url = app.config.get("OHIF_VIEWER_URL", "http://localhost:8080").rstrip("/")
        return {"ohif_base_url": ohif_base_url}


# ----------------------------------------------------
#  RUN APP
# ----------------------------------------------------
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)  # ✅ FIXED: dots not commas!
    
    
