from flask import Flask, render_template, session, url_for, redirect, request, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
from functools import wraps
from flask import send_from_directory
import os

from config import Config
from models import db, Patient, User, Scan, ActivityLog  # <-- import your db here
import pydicom
from PIL import Image
import numpy as np

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

app = Flask(__name__)
app.config.from_object(Config)


# Initialize application
db.init_app(app)
migrate = Migrate(app, db)

# Create Tables upon instance
#@app.before_first_request
#def create_tables():
#    db.create_all()

with app.app_context():
    db.create_all()

# Home Page Route
@app.route('/home')
@login_required
def home_page():
    return render_template('home.html')


# Registration Route
@app.route('/register-admin-user', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please fill in both fields!')
            return redirect(url_for('register'))
        
        user = User.query.filter_by(username=username).first()
        
        if user:
            flash('User already exists!')
            return redirect(url_for('login'))
        
        #create a new user with hashed password
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)

        db.session.add(new_user)
        db.session.commit()

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
            session['user_id'] = user.id  # optional: track session
            session['username'] = user.username 
            flash('Logged in successfully.')

            log = ActivityLog(
                action='Login',
                description=f'User {user.username} logged in.',
                user=user.username,
                timestamp=datetime.now()
            )
            db.session.add(log)
            db.session.commit()

            return redirect(url_for('home_page')) 
        else:
            flash('Invalid username or password.')
            return redirect(url_for('login'))

    return render_template('login.html')


# Upload Route
@app.route('/upload-scans', methods=['GET', 'POST'])
@login_required
def upload_scan():
    UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads', 'scans')
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpeg', 'jpg', 'dcm', 'tiff'}
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    def is_dicom(file_path):
        try:
            ds = pydicom.dcmread(file_path)
            return True
        except:
            return False

    def convert_dicom_to_jpeg(dicom_path, output_path):
        ds = pydicom.dcmread(dicom_path)
        pixel_array = ds.pixel_array

        pixel_array = pixel_array.astype(float)
        pixel_array -= pixel_array.min()
        if pixel_array.max() > 0:
            pixel_array /= pixel_array.max()
        pixel_array *= 255.0
        pixel_array = pixel_array.astype('uint8')

        image = Image.fromarray(pixel_array)
        image.save(output_path)

    dicom_metadata = {
        'modality': None,
        'study_date': None,
        'patient_name': None
    }

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['file']
        description = request.form.get('description')
        patient_id = request.form.get('patient_id')
        patient_id = int(patient_id) if patient_id else None

        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            filename = secure_filename(file.filename).lower()
            absolute_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(absolute_path)

            file_ext = filename.rsplit('.', 1)[1].lower()

            if file_ext == 'dcm' and is_dicom(absolute_path):
                ds = pydicom.dcmread(absolute_path)
                dicom_metadata['modality'] = getattr(ds, 'Modality', 'N/A')
                dicom_metadata['study_date'] = getattr(ds, 'StudyDate', 'N/A')
                dicom_metadata['patient_name'] = str(getattr(ds, 'PatientName', 'N/A'))

                # Convert to JPEG
                jpeg_preview_name = filename.rsplit('.', 1)[0] + '.jpg'
                jpeg_output_path = os.path.join(app.config['UPLOAD_FOLDER'], jpeg_preview_name)
                convert_dicom_to_jpeg(absolute_path, jpeg_output_path)

                relative_path = os.path.join('uploads', 'scans', jpeg_preview_name).replace("\\", "/")
            else:
                relative_path = os.path.join('uploads', 'scans', filename).replace("\\", "/")

            new_scan = Scan(
                file_name=filename,
                file_path=relative_path,
                file_type=file_ext,
                description=description,
                patient_id=patient_id,
                modality=dicom_metadata['modality'],
                study_date=dicom_metadata['study_date'],
                patient_name=dicom_metadata['patient_name']
            )
            db.session.add(new_scan)
            db.session.commit()

            flash('Scan uploaded successfully')
            return redirect(url_for('view_records'))

    return render_template('upload_scan.html')



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
    per_page = 6
    pagination = Scan.query.order_by(Scan.uploaded_at.desc()).paginate(page=page, per_page=per_page)
    scans = pagination.items

    for scan in scans:
        if scan.file_path:
            scan.filename = os.path.basename(scan.file_path)
        else:
            scan.filename = 'unknown_file'
            app.logger.warning(f'Missing file_path for scan ID: {scan.id}')

    return render_template('view_records.html', scans=scans, pagination=pagination)

# Patients
@app.route('/add-patient', methods=['GET','POST'])
@login_required
def add_patient():
    if request.method == 'POST':
        name = request.form.get('name')
        dob = request.form.get('dob')
        sex = request.form.get('sex')  # Capture this

        new_patient = Patient(name=name, dob=dob, sex=sex)
        db.session.add(new_patient)
        db.session.commit()
        flash('Patient added successfully.')
        return redirect(url_for('add_patient'))
    
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
        patients = Patient.query.filter(Patient.name.ilike(f"%{query}%")).all()

    return render_template('search_patient.html', patients=patients, query=query)


# View Images
@app.route('/view-images')
@login_required
def view_images():
    scans = Scan.query.filter(Scan.file_type.in_(['jpg', 'jpeg', 'png'])).all()
    return render_template('view_images.html', scans=scans)

# Logs Route
@app.route('/activity-logs')
@login_required
def view_logs():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template('activity_logs.html', logs=logs)

# Patient Scans
@app.route('/patient/<int:patient_id>/scans')
@login_required
def view_patient_scans(patient_id):
    page = request.args.get('page', 1, type=int)
    per_page = 6
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

#Edit Route
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

    for scan in patient.scans:
        db.session.delete(scan)

    db.session.delete(patient)
    db.session.commit()

    flash('Patient deleted successfully!')
    return redirect(url_for('list_patients'))

# Clear Scans
@app.route('/delete-all-scans')
@login_required
def delete_all_scans():
    from models import db, Scan
    scans = Scan.query.all()
    for scan in scans:
        db.session.delete(scan)
    db.session.commit()
    return "All scan records deleted!"

@app.route('/db-test')
def db_test():
    try:
        # Just a harmless query
        result = db.session.execute('SELECT 1')
        return '✅ DB connection successful!'
    except Exception as e:
        return f'❌ DB Error: {e}'

# Logout Route
@app.route('/logout')
def logout():
    username = session.get('username','Unknown')

    log = ActivityLog(
        action='Logout',
        description=f'User {username} logged out.',
        user=username
    )
    db.session.add(log)
    db.session.commit()

    session.pop('user_id', None)
    session.pop('username', None)

    flash('Logged out successfully.')
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
