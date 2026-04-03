from flask import Blueprint, request, jsonify, render_template
from Blueprints.auth.routes import login_required
from dicom_utils.activity_logger import log_activity
from models import db, Ward, Department, Patient, Study
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

wards_bp = Blueprint('wards_bp', __name__, url_prefix='/wards')

# ==================== DEPARTMENT ROUTES ====================

# List all departments
@wards_bp.route('/departments', methods=['GET'])
def list_departments():
    departments = Department.query.all()
    return jsonify([{
        'id': d.id,
        'name': d.department_name,
        'code': d.department_code,
        'ward_count': len(d.wards)
    } for d in departments])

# Create department
@wards_bp.route('/departments', methods=['POST'])
def create_department():
    data = request.json
    
    # Check if code already exists
    existing = Department.query.filter_by(department_code=data['code']).first()
    if existing:
        return jsonify({'error': 'Department code already exists'}), 400
    
    dept = Department(
        department_name=data['name'],
        department_code=data['code'],
        description=data.get('description')
    )
    db.session.add(dept)
    db.session.commit()
    
    return jsonify({
        'id': dept.id,
        'name': dept.department_name,
        'code': dept.department_code
    }), 201

# Update department
@wards_bp.route('/departments/<int:dept_id>', methods=['PUT'])
def update_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    data = request.json
    
    dept.department_name = data.get('name', dept.department_name)
    dept.description = data.get('description', dept.description)
    
    db.session.commit()
    return jsonify({'message': 'Department updated'})

# Delete department
@wards_bp.route('/departments/<int:dept_id>', methods=['DELETE'])
def delete_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    
    # Check if has wards
    if len(dept.wards) > 0:
        return jsonify({'error': 'Cannot delete department with wards'}), 400
    
    db.session.delete(dept)
    db.session.commit()
    return jsonify({'message': 'Department deleted'})

# ==================== WARD ROUTES ====================

# List all wards
@wards_bp.route('/', methods=['GET'])
def list_wards():
    department_id = request.args.get('department_id')
    
    query = Ward.query
    if department_id:
        query = query.filter_by(department_id=department_id)
    
    wards = query.all()
    return jsonify([{
        'id': w.id,
        'name': w.ward_name,
        'code': w.ward_code,
        'department': w.department.department_name if w.department else None,
        'patient_count': len(w.patients)
    } for w in wards])

# Create ward
@wards_bp.route('/wards', methods=['POST'])
def create_ward():
    data = request.json
    
    # Check if code already exists
    existing = Ward.query.filter_by(ward_code=data['code']).first()
    if existing:
        return jsonify({'error': 'Ward code already exists'}), 400
    
    ward = Ward(
        ward_name=data['name'],
        ward_code=data['code'],
        department_id=data['department_id']
    )
    db.session.add(ward)
    db.session.commit()
    
    return jsonify({
        'id': ward.id,
        'name': ward.ward_name,
        'code': ward.ward_code
    }), 201

# Update ward
@wards_bp.route('/wards/<int:ward_id>', methods=['PUT'])
def update_ward(ward_id):
    ward = Ward.query.get_or_404(ward_id)
    data = request.json
    
    ward.ward_name = data.get('name', ward.ward_name)
    ward.department_id = data.get('department_id', ward.department_id)
    
    db.session.commit()
    return jsonify({'message': 'Ward updated'})

# Delete ward
@wards_bp.route('/wards/<int:ward_id>', methods=['DELETE'])
def delete_ward(ward_id):
    ward = Ward.query.get_or_404(ward_id)
    
    # Check if has patients
    if len(ward.patients) > 0:
        return jsonify({'error': f'Cannot delete ward with {len(ward.patients)} patients'}), 400
    
    db.session.delete(ward)
    db.session.commit()
    return jsonify({'message': 'Ward deleted'})

# ==================== PATIENT & STUDY ROUTES ====================

# Get patients in a ward
@wards_bp.route('/<int:ward_id>/patients', methods=['GET'])
def ward_patients(ward_id):
    ward = Ward.query.get_or_404(ward_id)
    patients = Patient.query.filter_by(ward_id=ward_id).all()
    
    return jsonify({
        'ward': {
            'id': ward.id,
            'name': ward.ward_name,
            'department': ward.department.department_name if ward.department else None
        },
        'patients': [{
            'id': p.id,
            'patient_id': p.patient_id,
            'name': p.patient_name,
            'study_count': len(p.studies)
        } for p in patients]
    })

# Get studies for a ward (worklist)
@wards_bp.route('/<int:ward_id>/studies', methods=['GET'])
def ward_studies(ward_id):
    ward = Ward.query.get_or_404(ward_id)
    q = (request.args.get("q") or "").strip()

    query = Study.query.join(Patient).filter(Patient.ward_id == ward_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Patient.patient_id.ilike(like),
                Patient.patient_name.ilike(like),
                Study.study_instance_uid.ilike(like),
                Study.description.ilike(like),
            )
        )

    studies = query.order_by(Study.study_date.desc()).all()
    
    return jsonify({
        'ward': ward.ward_name,
        'studies': [{
            'study_uid': s.study_instance_uid,
            'patient_id': s.patient.patient_id,
            'patient_name': s.patient.patient_name,
            'study_date': s.study_date,
            'description': s.description,
            'series_count': len(s.series)
        } for s in studies]
    })

# Transfer patient to different ward
@wards_bp.route('/patients/<int:patient_id>/transfer', methods=['POST'])
def transfer_patient(patient_id):
    data = request.json
    new_ward_id = data.get('ward_id')
    
    patient = Patient.query.get_or_404(patient_id)
    old_ward = patient.ward.ward_name if patient.ward else 'Unassigned'
    
    patient.ward_id = new_ward_id
    db.session.commit()
    
    new_ward = patient.ward.ward_name if patient.ward else 'Unassigned'

    log_activity(
        "patient_transfer",
        resource=f"patient_{patient.patient_id}",
        details=f"Transferred from {old_ward} to {new_ward}"
    )
    
    return jsonify({
        'message': f'Patient transferred from {old_ward} to {new_ward}',
        'patient_id': patient.patient_id,
        'new_ward': new_ward
    })


# Get patient by patient_id (not database id)
@wards_bp.route('/patients/by-patient-id/<patient_id>', methods=['GET'])
def get_patient_by_patient_id(patient_id):
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    
    return jsonify({
        'id': patient.id,
        'patient_id': patient.patient_id,
        'patient_name': patient.patient_name,
        'ward_id': patient.ward_id,
        'ward_name': patient.ward.ward_name if patient.ward else None
    })

# ==================== UI PAGES ====================

# Ward worklist UI page
@wards_bp.route('/worklist', methods=['GET'])
@login_required
def worklist_page():
    return render_template('ward_worklist.html')

# Management UI page
@wards_bp.route('/manage', methods=['GET'])
@login_required
def manage_page():
    return render_template('manage_wards.html')
