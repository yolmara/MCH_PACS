from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session, current_app
from Blueprints.auth.routes import login_required
from models import db, ExamOrder, Patient, Ward, User, Series
from datetime import datetime

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
    
    # Base query - orders that are completed but don't have reports yet
    from models import Study, RadiologyReport
    
    query = db.session.query(Study).join(Patient).outerjoin(
        RadiologyReport, Study.id == RadiologyReport.study_id_fk
    ).filter(RadiologyReport.id == None)  # No report yet
    
    if ward_id:
        query = query.filter(Patient.ward_id == ward_id)
    
    if modality:
        query = query.join(Series).filter(Series.modality == modality)
    
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
        flash("Report updated successfully!", "success")
        return redirect(url_for("ris_bp.view_report", report_id=report.id))
    
    return render_template("ris/report_form.html", study=report.study, report=report)
