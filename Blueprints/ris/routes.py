from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session, current_app
from Blueprints.auth.routes import login_required
from dicom_utils.activity_logger import log_activity
from models import db, ExamOrder, Patient, Ward, User, Series, Appointment
from datetime import datetime
from sqlalchemy import or_




ris_bp = Blueprint("ris_bp", __name__)

# =====================================================
# EXAM ORDERING (for doctors)
# =====================================================

@ris_bp.route("/orders", methods=["GET"])
@login_required
def list_orders():
    """View all exam orders"""
    orders = ExamOrder.query.order_by(ExamOrder.order_date.desc()).all()
    return render_template("ris/orders_list.html", orders=orders)


@ris_bp.route("/orders/new/<int:patient_id>", methods=["GET", "POST"])
@login_required
def create_order(patient_id):
    """Create new exam order for a patient"""
    patient = Patient.query.get_or_404(patient_id)
    
    if request.method == "POST":
        # Generate order number
        order_count = ExamOrder.query.count() + 1
        order_number = f"ORD{datetime.now().strftime('%Y%m%d')}{order_count:04d}"
        
        order = ExamOrder(
            order_number=order_number,
            patient_id_fk=patient.id,
            ordering_doctor_id=session.get("user_id"),
            ordering_doctor_name=request.form.get("doctor_name"),
            exam_type=request.form.get("exam_type"),
            body_part=request.form.get("body_part"),
            clinical_indication=request.form.get("clinical_indication"),
            priority=request.form.get("priority", "routine"),
            ward_id=patient.ward_id,
            status="pending"
        )
        
        db.session.add(order)
        db.session.commit()
        
        flash(f"Exam order {order_number} created successfully!", "success")
        return redirect(url_for("ris_bp.list_orders"))
    
    # GET request - show form
    return render_template("ris/order_form.html", patient=patient)


@ris_bp.route("/orders/<int:order_id>", methods=["GET"])
@login_required
def view_order(order_id):
    """View single exam order details"""
    order = ExamOrder.query.get_or_404(order_id)
    return render_template("ris/order_detail.html", order=order)


@ris_bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id):
    """Cancel an exam order"""
    order = ExamOrder.query.get_or_404(order_id)
    order.status = "cancelled"
    db.session.commit()
    
    flash(f"Order {order.order_number} cancelled", "info")
    return redirect(url_for("ris_bp.list_orders"))


# =====================================================
# WORKLIST (for radiologists and technicians)
# =====================================================

@ris_bp.route("/worklist", methods=["GET"])
@login_required
def worklist():
    """View pending studies needing reports"""
    # Get filters
    ward_id = request.args.get("ward_id")
    modality = request.args.get("modality")
    search_query = (request.args.get("q") or "").strip()
    
    # Base query - orders that are completed but don't have reports yet
    from models import Study, RadiologyReport
    
    query = db.session.query(Study).join(Patient).outerjoin(
        RadiologyReport, Study.id == RadiologyReport.study_id_fk
    ).filter(RadiologyReport.id == None)  # No report yet
    
    if ward_id:
        query = query.filter(Patient.ward_id == ward_id)
    
    if modality:
        query = query.join(Series).filter(Series.modality == modality)

    if search_query:
        query = query.filter(
            or_(
                Patient.patient_id.ilike(f"%{search_query}%"),
                Patient.patient_name.ilike(f"%{search_query}%"),
                Study.study_instance_uid.ilike(f"%{search_query}%"),
                Study.description.ilike(f"%{search_query}%"),
            )
        )

    query = query.distinct()

    studies = query.all()
    wards = Ward.query.all()
    
    return render_template("ris/worklist.html", studies=studies, wards=wards)

# =====================================================
# REPORTING (for radiologists)
# =====================================================

@ris_bp.route("/reports/new/<int:study_id>", methods=["GET", "POST"])
@login_required
def create_report(study_id):
    """Create new radiology report for a study"""
    from models import Study, RadiologyReport
    
    study = Study.query.get_or_404(study_id)
    
    if request.method == "POST":
        try:
            report = RadiologyReport(
                study_id_fk=study.id,
                radiologist_id=session.get("user_id"),
                radiologist_name=request.form.get("radiologist_name") or session.get("full_name"),
                findings=request.form.get("findings"),
                impression=request.form.get("impression"),
                recommendations=request.form.get("recommendations"),
                status=request.form.get("status", "draft")
            )
            
            if report.status == "final":
                report.finalized_at = datetime.now()
            
            db.session.add(report)
            db.session.commit()

            log_activity(
                "report_written",
                resource=f"study_{study.study_instance_uid}",
                details=f"Report {report.id} created with status {report.status}"
            )
            
            flash("Report saved successfully!", "success")
            return redirect(url_for("ris_bp.view_report", report_id=report.id))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to save report for study %s", study_id)
            flash("Failed to save report. Please try again.", "error")
            return render_template("ris/report_form.html", study=study, report=None), 500
    
    # GET - show form
    return render_template("ris/report_form.html", study=study)


@ris_bp.route("/reports/<int:report_id>", methods=["GET"])
@login_required
def view_report(report_id):
    """View a radiology report"""
    from models import RadiologyReport
    
    report = RadiologyReport.query.get_or_404(report_id)
    log_activity(
        "report_viewed",
        resource=f"report_{report.id}",
        details=f"Viewed report for study {report.study.study_instance_uid}"
    )
    return render_template("ris/report_view.html", report=report)


@ris_bp.route("/reports/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def edit_report(report_id):
    """Edit an existing report"""
    from models import RadiologyReport
    
    report = RadiologyReport.query.get_or_404(report_id)
    
    if request.method == "POST":
        report.findings = request.form.get("findings")
        report.impression = request.form.get("impression")
        report.recommendations = request.form.get("recommendations")
        report.status = request.form.get("status", "draft")
        
        if report.status == "final" and not report.finalized_at:
            report.finalized_at = datetime.now()
        
        db.session.commit()
        log_activity(
            "report_updated",
            resource=f"report_{report.id}",
            details=f"Updated report status to {report.status}"
        )
        flash("Report updated successfully!", "success")
        return redirect(url_for("ris_bp.view_report", report_id=report.id))
    
    return render_template("ris/report_form.html", study=report.study, report=report)



#======================================================#
#               Apponintment Scheduling     
#======================================================#

VALID_APPT_STATUSES = {"scheduled", "arrived", "in_progress", "completed", "cancelled", "no_show"}

def _parse_dt(value: str):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")

def _has_overlap(resource_name, start_dt, end_dt, exclude_id=None):
    q = Appointment.query.filter(
        Appointment.resource_name == resource_name,
        Appointment.status.in_(["scheduled", "arrived", "in_progress"]),
        Appointment.scheduled_start < end_dt,
        Appointment.scheduled_end > start_dt,
    )
    if exclude_id:
        q = q.filter(Appointment.id != exclude_id)
    return db.session.query(q.exists()).scalar()

@ris_bp.route("/schedule", methods=["GET"])
@login_required
def schedule_board():
    date_str = request.args.get("date")
    modality = request.args.get("modality")
    status = request.args.get("status")
    q = (request.args.get("q") or "").strip()

    query = Appointment.query.join(Patient)

    if date_str:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        query = query.filter(Appointment.scheduled_start >= day_start, Appointment.scheduled_start <= day_end)

    if modality:
        query = query.filter(Appointment.modality == modality)
    if status:
        query = query.filter(Appointment.status == status)
    if q:
        query = query.filter(
            db.or_(
                Patient.patient_id.ilike(f"%{q}%"),
                Patient.patient_name.ilike(f"%{q}%"),
                Appointment.resource_name.ilike(f"%{q}%"),
            )
        )

    appointments = query.order_by(Appointment.scheduled_start.asc()).all()
    return render_template("ris/schedule_board.html", appointments=appointments)

@ris_bp.route("/schedule", methods=["POST"])
@login_required
def create_appointment():
    patient_id_fk = int(request.form["patient_id_fk"])
    modality = request.form["modality"].strip()
    resource_name = request.form["resource_name"].strip()
    start_dt = _parse_dt(request.form["scheduled_start"])
    end_dt = _parse_dt(request.form["scheduled_end"])
    notes = request.form.get("notes", "")
    order_id_fk = request.form.get("order_id_fk") or None

    if end_dt <= start_dt:
        flash("End time must be after start time", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    if _has_overlap(resource_name, start_dt, end_dt):
        flash("Time conflict: scanner/resource already booked", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    appt = Appointment(
        patient_id_fk=patient_id_fk,
        order_id_fk=int(order_id_fk) if order_id_fk else None,
        modality=modality,
        resource_name=resource_name,
        scheduled_start=start_dt,
        scheduled_end=end_dt,
        status="scheduled",
        notes=notes,
        created_by_user_id=session.get("user_id"),
    )
    db.session.add(appt)

    if appt.order_id_fk:
        order = ExamOrder.query.get(appt.order_id_fk)
        if order:
            order.status = "scheduled"

    db.session.commit()

    log_activity(
        "appointment_created",
        resource=f"appointment_{appt.id}",
        details=f"patient={appt.patient_id_fk}, modality={appt.modality}, start={appt.scheduled_start}"
    )

    flash("Appointment created", "success")
    return redirect(url_for("ris_bp.schedule_board"))

@ris_bp.route("/schedule/<int:appointment_id>/status", methods=["POST"])
@login_required
def update_appointment_status(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    new_status = request.form.get("status", "").strip()

    if new_status not in VALID_APPT_STATUSES:
        flash("Invalid status", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    allowed = {
        "scheduled": {"arrived", "cancelled", "no_show"},
        "arrived": {"in_progress", "cancelled"},
        "in_progress": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
        "no_show": set(),
    }
    if new_status not in allowed.get(appt.status, set()):
        flash(f"Invalid transition from {appt.status} to {new_status}", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    old = appt.status
    appt.status = new_status

    if appt.order:
        if new_status == "in_progress":
            appt.order.status = "in_progress"
        elif new_status == "completed":
            appt.order.status = "completed"
            appt.order.completed_date = datetime.utcnow()
        elif new_status == "cancelled":
            appt.order.status = "cancelled"

    db.session.commit()

    log_activity(
        "appointment_status_changed",
        resource=f"appointment_{appt.id}",
        details=f"{old} -> {new_status}"
    )

    flash("Appointment status updated", "success")
    return redirect(url_for("ris_bp.schedule_board"))

@ris_bp.route("/schedule/<int:appointment_id>/reschedule", methods=["POST"])
@login_required
def reschedule_appointment(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    start_dt = _parse_dt(request.form["scheduled_start"])
    end_dt = _parse_dt(request.form["scheduled_end"])

    if end_dt <= start_dt:
        flash("End time must be after start time", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    if _has_overlap(appt.resource_name, start_dt, end_dt, exclude_id=appt.id):
        flash("Time conflict on selected resource", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    old_start = appt.scheduled_start
    appt.scheduled_start = start_dt
    appt.scheduled_end = end_dt
    appt.status = "scheduled"
    db.session.commit()

    log_activity(
        "appointment_rescheduled",
        resource=f"appointment_{appt.id}",
        details=f"{old_start} -> {start_dt}"
    )

    flash("Appointment rescheduled", "success")
    return redirect(url_for("ris_bp.schedule_board"))
