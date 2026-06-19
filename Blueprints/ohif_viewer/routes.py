from flask import Blueprint, redirect, current_app
from Blueprints.auth.routes import login_required

pacs_bp = Blueprint("pacs_bp", __name__)

@pacs_bp.route("/study/<study_uid>/view")
@login_required
def view_study(study_uid):
    # For now: no login/auth and no logging
    # Redirect to the configured OHIF viewer endpoint.
    ohif_base_url = current_app.config.get("OHIF_VIEWER_URL", "http://localhost:8081/ohif/").rstrip("/")
    return redirect(f"{ohif_base_url}/viewer?StudyInstanceUIDs={study_uid}")
