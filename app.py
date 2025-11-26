import os
from datetime import datetime, timedelta
from functools import wraps

import numpy as np
import pydicom
import io
from dotenv import load_dotenv
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   send_from_directory, send_file, session, url_for)
from flask_login import LoginManager, current_user, login_user, logout_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from PIL import Image
from pytz import timezone, utc
from pyuploadcare import Uploadcare
from sqlalchemy import or_, func
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config
from models import (ActivityLog, Patient, Scan,  # <-- import your db here
                    User, db)

load_dotenv()

# Admin Token
admin_token = ''

# Admin Required
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Access denied: Admins only.', 'danger')
            return redirect(url_for('home_page'))
        return f(*args, **kwargs)
    return decorated_function

#Login required helper
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            print("No session found. Redirecting.")
            flash('Please log in to access this page.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# convert to CAT time zone
def cat_time_filter(utc_dt, fmt='%Y-%m-%d %H:%M:%S'):
    if utc_dt is None:
        return ''
    cat = timezone('Africa/Harare')
    local_dt = utc_dt.replace(tzinfo=utc).astimezone(cat)
    return local_dt.strftime(fmt)

app = Flask(__name__)
app.config.from_object(Config)
app.jinja_env.filters['cat_time'] = cat_time_filter

#Uploadcare Configuration
uploadcare = Uploadcare(public_key='83de91569ee2a4d5f898', secret_key='e067cc474783f6d55ebb')

# Initialize application
db.init_app(app)
migrate = Migrate(app, db)

# Login Manager configuration
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

#####################################
############### ROUTES ##############
#####################################

# Activity Logs Route
@app.route("/activity-logs")
@admin_required
@login_required
def activity_logs():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template("activity_logs.html", logs=logs)


# Home Page Route
@app.route('/home')
@login_required
def home_page():
    return render_template('home.html')

# Registration Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        selected_role = request.form.get('role', 'user')  # user or admin
        admin_token = request.form.get('admin_token', '')

        role = 'user'

        if selected_role == 'admin' and admin_token == 'admins@pacs':
            role = 'admin'
        

        # Save user
        user = User(username=username, password=password, role=role)
        db.session.add(user)
        db.session.commit()

        flash(f'Account created successfully as {role}', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# Login Route
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)

            # Store user details in session
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role  # correctly store role

            flash('Logged in successfully!', 'success')

            # Log the login action
            logs = ActivityLog(
                action='login',
                description=f'User {username} logged in.',
                user=username
            )
            db.session.add(logs)
            db.session.commit()

            # Debugging - print role to console
            print(f"✅ {user.username} logged in with role: {user.role}")

            return redirect(url_for('home_page'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')



# Upload Route
@app.route('/upload_scan', methods=['GET', 'POST'])
@login_required
def upload_scan():
    UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads', 'scans')
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpeg', 'jpg', 'dcm', 'tiff'}
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    def is_dicom(file_path):
        try:
            ds = pydicom.dcmread(file_path)
            return True
        except Exception as e:
            print("Not a valid DICOM:", e)
            return False

    def convert_dicom_to_jpeg(dicom_path, jpeg_path):
        try:
            ds = pydicom.dcmread(dicom_path)
            if 'PixelData' in ds:
                pixel_array = ds.pixel_array
                image = Image.fromarray(pixel_array)
                image = image.convert('L')
                image.save(jpeg_path)
        except Exception as e:
            print("DICOM to JPEG conversion error:", e)

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part in the request', 'danger')
            return redirect(request.url)

        file = request.files['file']
        description = request.form.get('description')
        patient_id = request.form.get('patient_id')
        mch_number = request.form.get('mch_number', '').strip()
        national_id = request.form.get('national_id', '').strip()

        if file.filename == '':
            flash('No file selected for uploading', 'danger')
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash('File type not allowed', 'danger')
            return redirect(request.url)

        try:
            patient_id = int(patient_id) if patient_id else None
        except ValueError:
            flash('Invalid patient ID', 'danger')
            return redirect(request.url)

        filename = secure_filename(file.filename.lower())
        absolute_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(absolute_path)
        file_ext = filename.rsplit('.', 1)[1].lower()

        jpeg_preview_name = None
        modality = study_date = patient_name = 'N/A'

        if file_ext == 'dcm' and is_dicom(absolute_path):
            ds = pydicom.dcmread(absolute_path)
            modality = getattr(ds, 'Modality', 'N/A')
            study_date = getattr(ds, 'StudyDate', 'N/A')
            patient_name = str(getattr(ds, 'PatientName', 'N/A'))

            # Generate preview
            jpeg_preview_name = filename.replace('.dcm', '.jpg')
            jpeg_path = os.path.join(UPLOAD_FOLDER, jpeg_preview_name)
            convert_dicom_to_jpeg(absolute_path, jpeg_path)

        # Save record in DB
        new_scan = Scan(
            file_name=filename,
            file_type=file_ext,
            file_path=filename,  # now just storing the filename
            jpeg_preview_url=jpeg_preview_name,  # preview filename if exists
            description=description,
            patient_id=patient_id,
            modality=modality,
            timestamp=datetime.utcnow(),
            study_date=study_date,
            patient_name=patient_name,
        )
        db.session.add(new_scan)
        db.session.commit()

        flash('Scan uploaded successfully')
        return redirect(url_for('view_records'))

    # For GET
    patients = Patient.query.all()
    return render_template('upload_scans.html', patients=patients)



# Uploaded Files
@app.route('/uploads/scans/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory('static/uploads/scans', filename)


# View Records
@app.route('/view-records')
@login_required
def view_records():
    page = request.args.get('page', 1, type=int)
    per_page = 8
    pagination = Scan.query.order_by(Scan.uploaded_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    scans = pagination.items

    for scan in scans:
        if scan.file_path:
            # Create a static-accessible URL for sharing
            scan.file_url = url_for('static', filename='uploads/scans/' + scan.file_name, _external=True)

            scan.filename = os.path.basename(scan.file_path)

            # DICOM preview
            if scan.filename.endswith('.dcm'):
                scan.jpg_preview = scan.filename.replace('.dcm', '.jpg')

    return render_template('view_records.html', scans=scans, pagination=pagination)

# View Images
@app.route('/view-images')
@login_required
def view_images():
    page = request.args.get('page', 1, type=int)
    pagination = Scan.query.filter(
        Scan.file_type.in_(['jpg', 'jpeg', 'png'])
    ).order_by(Scan.uploaded_at.desc()).paginate(page=page, per_page=6)
    scans = pagination.items
    
    return render_template('view_images.html', scans=scans, pagination=pagination)


# Add Patients
@app.route('/add-patient', methods=['GET','POST'])
@login_required
def add_patient():
    if request.method == 'POST':
        name = request.form.get('name')
        dob = request.form.get('dob')
        sex = request.form.get('sex')  
        national_id = request.form.get('national_id')
        mch_number = request.form.get('mch_number')

        new_patient = Patient(name=name, dob=dob, sex=sex, national_id=national_id, mch_number=mch_number)
        db.session.add(new_patient)
        db.session.commit()
        flash('Patient added successfully.')
        return redirect(url_for('upload_scan'))
    
    return render_template('add_patient.html')


# Record debugger    
@app.route('/debug-scans')
def debug_scans():
    scans = Scan.query.all()
    return f"Found {len(scans)} scans"


# Delete Scans
@app.route('/delete-scan/<int:scan_id>', methods=['POST'])
@login_required
def delete_scan(scan_id):
    scan = Scan.query.get_or_404(scan_id)
    
    # Delete the file from the static folder
    file_path = os.path.join(app.static_folder, scan.file_path)
    if os.path.exists(file_path):
        os.remove(file_path)

    # Delete from database
    db.session.delete(scan)
    
    log = ActivityLog(
        action='Delete',
        description=f'Deleted scan: {scan.file_name}',
        user=session.get('username', 'Unknown')
        )
    db.session.add(log)
    db.session.commit()

    flash('Scan deleted successfully!')
    return redirect(url_for('view_records'))


#Search Patient
@app.route('/search-patients', methods=['GET', 'POST'])
@login_required
def search_patient():
    query = request.form.get('query', '')

    patients = []
    if query:
        patients = Patient.query.filter(
            or_(
                Patient.name.ilike(f"%{query}%"),
                Patient.national_id.ilike(f"%{query}%"),
                Patient.mch_number.ilike(f"%{query}%")
            )
        ).all()

        if not patients:
            flash(f'No patient records found for "{query}".')

    return render_template('search_patient.html', patients=patients, query=query)


# Patient Scans
@app.route('/patient/<int:patient_id>/scans')
@login_required
def view_patient_scans(patient_id):
    page = request.args.get('page', 1, type=int)
    per_page = 8
    patient = Patient.query.get_or_404(patient_id)

    pagination = Scan.query.filter_by(patient_id=patient_id).paginate(page=page, per_page=per_page)
    scans = pagination.items

    return render_template('patient_scans.html', patient=patient, scans=scans, pagination=pagination)

# Patient Records after Patient search
@app.route('/patient-records/<int:patient_id>')
@login_required
def patient_records(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    scans = Scan.query.filter_by(patient_id=patient_id).all()

    return render_template('patient_records.html', patient=patient, scans=scans)

#Edit Scan Route
@app.route('/edit-scan/<int:scan_id>', methods=['GET', 'POST'])
@login_required
def edit_scan(scan_id):
    scan = Scan.query.get_or_404(scan_id)
    patients = Patient.query.all()  # To repopulate the dropdown

    if request.method == 'POST':
        scan.description = request.form['description']
        patient_id = request.form.get('patient_id')
        scan.patient_id = int(patient_id) if patient_id else None

        log = ActivityLog(
            action='Edit',
            description=f'Edited scan: {scan.file_name}',
            user=session.get('username', 'Unknown')
        )
        db.session.add(log)
        db.session.commit()

        flash('Scan updated successfully!')
        return redirect(url_for('view_records'))

    return render_template('edit_scan.html', scan=scan, patients=patients)

# Edit Patient Name
@app.route('/edit-patient/<int:patient_id>', methods=['GET', 'POST'])
def edit_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)

    if request.method == 'POST':
        try:
            patient.name = request.form['name']
            patient.dob = request.form['dob']
            patient.sex = request.form['sex']
            patient.national_id = request.form['national_id']
            patient.mch_number = request.form['mch_number']

            db.session.commit()
            flash('Patient updated successfully!', 'success')
            return redirect(url_for('list_patients')) 
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating patient: {str(e)}', 'danger')

    return render_template('edit_patient_name.html', patient=patient)

# List Patient
@app.route('/patients', methods=['GET', 'POST'])
@login_required
def list_patients():
    search_query = request.form.get('search', '').strip()
    if search_query:
        patients = Patient.query.filter(Patient.name.ilike(f"%{search_query}%")).all()
    else:
        patients = Patient.query.all()

    return render_template('list_patients.html', patients=patients, search_query=search_query)
    

# Delete Patient
@app.route('/delete-patient/<int:patient_id>', methods=['POST'] )
@login_required
def delete_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)

    for scan in patient.records:
        db.session.delete(scan)

    db.session.delete(patient)
    db.session.commit()

    flash('Patient deleted successfully!')
    return redirect(url_for('list_patients'))


# Clear Scans
@app.route('/delete-all-scans')
@login_required
def delete_all_scans():
    from models import Scan, db
    scans = Scan.query.all()
    for scan in scans:
        db.session.delete(scan)
    db.session.commit()
    return "All scan records deleted!"

# delete users
@app.route('/delete-all-users')
@login_required
def delete_all_users():
    if current_user.role != 'admin':  # only admins can trigger
        flash("Unauthorized action!", "danger")
        return redirect(url_for('home_page'))

    # Delete all users
    User.query.delete()
    db.session.commit()

    flash("All users have been deleted. Please register a new account.", "success")
    return redirect(url_for('login'))


# Manage Users
@app.route('/manage-users')
@admin_required
def manage_users():
    users = User.query.all()
    return render_template("manage_users.html", users=users)


@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.username == "coder911":
        flash("You cannot delete the primary admin !!!", "danger")
        return redirect(url_for("manage_users"))

    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} deleted successfully.", "success")
    return redirect(url_for("manage_users"))

# Scan Stats
@app.route('/scan-stats')
@login_required
@admin_required
def scan_stats():
    # Initialize counters
    counts = {
        'MR': 0,
        'CT': 0,
        'X-Ray': 0,
        'PDF': 0,
        'PNG/JPG': 0
    }

    scans = Scan.query.all()
    for scan in scans:
        # Count DICOM modalities if file_type is dcm
        if scan.file_name.endswith('.dcm') and scan.modality:
            mod = scan.modality.upper()
            if 'MR' in mod:
                counts['MR'] += 1
            elif 'CT' in mod:
                counts['CT'] += 1
            elif 'XRAY' in mod or 'X-RAY' in mod:
                counts['X-Ray'] += 1
        else:
            ext = scan.file_name.split('.')[-1].lower()
            if ext in ['pdf']:
                counts['PDF'] += 1
            elif ext in ['png', 'jpg']:
                counts['PNG/JPG'] += 1

    return render_template('scan_stats.html', counts=counts)


# Report Generation
@app.route('/reports', methods=['GET', 'POST'])
@login_required
@admin_required
def reports():
    # Default date range (last 7 days)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)

    if request.method == 'GET':
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')
        if start_str and end_str:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d')

    # POST downloads PDF
    if request.method == 'POST':
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')
        if start_str and end_str:
            start_date = datetime.strptime(start_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_str, "%Y-%m-%d")

        if "download_pdf" in request.form:
            return generate_report_pdf(start_date, end_date)
    
    
    # Query scan stats
    scans_by_type = (
        db.session.query(Scan.file_type, func.count(Scan.id))
        .filter(Scan.uploaded_at >= start_date, Scan.uploaded_at <= end_date)
        .group_by(Scan.file_type)
        .all()
    )
    
    type_counts = {ft.lower(): count for ft, count in scans_by_type}

    mri_count = type_counts.get("mr", 0)
    ct_count = type_counts.get("ct", 0)
    xray_count = type_counts.get("x-ray", 0)
    pdf_count = type_counts.get("pdf", 0)
    png_count = type_counts.get("png", 0) + type_counts.get("jpg", 0)


    labels = [ft.upper() for ft, _ in scans_by_type]
    data = [count for _, count in scans_by_type]

    # Summary counts
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    daily_count = Scan.query.filter(func.date(Scan.uploaded_at) == today).count()
    weekly_count = Scan.query.filter(Scan.uploaded_at >= week_start).count()
    monthly_count = Scan.query.filter(Scan.uploaded_at >= month_start).count()

    return render_template(
        'reports.html',
        daily_count=daily_count,
        weekly_count=weekly_count,
        monthly_count=monthly_count,
        scans_by_type=scans_by_type,
        labels=labels,
        data=data,
        mri_count = mri_count,
        ct_count = ct_count,
        xray_count = xray_count,
        pdf_count = pdf_count,
        png_count = png_count,
        start_date=start_date.date(),
        end_date=end_date.date()
    )

def generate_report_pdf(start_date, end_date):
    """Generate downloadable PDF summary report."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    title = Paragraph(f"<b>System Summary Report</b>", styles["Title"])
    story.append(title)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Reporting Period: {start_date.date()} to {end_date.date()}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Query data again
    scans_by_type = (
        db.session.query(Scan.file_type, func.count(Scan.id))
        .filter(Scan.uploaded_at >= start_date, Scan.uploaded_at <= end_date)
        .group_by(Scan.file_type)
        .all()
    )

    # Table data
    data = [["File Type", "Total Scans"]]
    for file_type, count in scans_by_type:
        data.append([file_type.upper(), count])

    table = Table(data, colWidths=[200, 200])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4B9CD3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(table)

    doc.build(story)
    buffer.seek(0)

    filename = f"System_Report_{start_date.date()}_to_{end_date.date()}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
    

    
# Logout Route
@app.route('/logout')
@login_required
def logout():
    username = current_user.username  # for logging purposes
    logout_user()  # Flask-Login clears the session for us

    # Log the logout activity
    logs = ActivityLog(
        action='logout',
        description=f'User {username} logged out.',
        user=username
    )
    db.session.add(logs)
    db.session.commit()

    flash('You have been logged out.')
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
