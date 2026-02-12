from flask import Blueprint, render_template
from Blueprints.auth.routes import login_required
from models import Patient, Study, Ward

home_bp = Blueprint('home_bp', __name__)

@home_bp.route("/")
@login_required
def home_page():
    stats = {
        "patients": Patient.query.count(),
        "studies": Study.query.count(),
        "wards": Ward.query.count(),
    }
    return render_template('home.html', stats=stats)

