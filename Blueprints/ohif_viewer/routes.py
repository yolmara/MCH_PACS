from flask import Blueprint, redirect

pacs_bp = Blueprint("pacs_bp", __name__)

@pacs_bp.route("/study/<study_uid>/view")
def view_study(study_uid):
    # For now: no login/auth and no logging
    # Simply redirect to OHIF viewer via reverse proxy
    return redirect(f"/viewer/?StudyInstanceUID={study_uid}")
