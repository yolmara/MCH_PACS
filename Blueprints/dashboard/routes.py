from flask import Blueprint, render_template, request, jsonify
from Blueprints.auth.routes import login_required

home_bp = Blueprint('home_bp', __name__)

@home_bp.route("/")
@login_required
def home_page():
    return render_template('home.html')


