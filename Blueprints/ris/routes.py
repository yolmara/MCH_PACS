from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session, current_app, send_file
from Blueprints.auth.routes import login_required
from dicom_utils.activity_logger import log_activity
from models import db, ExamOrder, Patient, Ward, User, Series, Appointment, RadiologyReport
from datetime import datetime
from sqlalchemy import or_
from io import BytesIO
import shutil
from html import unescape
import re
import textwrap
import os
from uuid import uuid4
from pytz import timezone, utc
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from werkzeug.utils import secure_filename




ris_bp = Blueprint("ris_bp", __name__)


@ris_bp.context_processor
def inject_ris_draft_count():
    """Expose draft report count for RIS navigation."""
    user_id = session.get("user_id")
    view_functions = getattr(current_app, "view_functions", {})
    has_saved_reports_endpoint = "ris_bp.list_saved_reports" in view_functions
    has_pdf_endpoint = "ris_bp.download_report_pdf" in view_functions
    if not user_id:
        return {
            "ris_draft_count": 0,
            "ris_has_saved_reports_endpoint": has_saved_reports_endpoint,
            "ris_has_pdf_endpoint": has_pdf_endpoint,
        }

    query = RadiologyReport.query.filter(RadiologyReport.status == "draft")
    if session.get("role") != "admin":
        query = query.filter(RadiologyReport.radiologist_id == user_id)

    return {
        "ris_draft_count": query.count(),
        "ris_has_saved_reports_endpoint": has_saved_reports_endpoint,
        "ris_has_pdf_endpoint": has_pdf_endpoint,
    }


def _is_report_accessible(report):
    """Admins can access all reports; radiologists can access their own."""
    if session.get("role") == "admin":
        return True
    return report.radiologist_id == session.get("user_id")


def _format_cat_time(dt_obj):
    if not dt_obj:
        return "N/A"
    if dt_obj.tzinfo is None:
        dt_obj = utc.localize(dt_obj)
    return dt_obj.astimezone(timezone("Africa/Harare")).strftime("%Y-%m-%d %H:%M")


def _strip_html(value):
    value = value or ""
    return unescape(re.sub(r"<[^>]+>", "", value))


ALLOWED_SCREENSHOT_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def _is_allowed_screenshot(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_SCREENSHOT_EXTENSIONS


def _report_screenshot_dir(report_id):
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "reports", str(report_id), "screenshots")


def _report_screenshot_assets(report_id):
    assets = []
    directory = _report_screenshot_dir(report_id)
    if not os.path.isdir(directory):
        return assets

    for filename in sorted(os.listdir(directory)):
        if not _is_allowed_screenshot(filename):
            continue
        full_path = os.path.join(directory, filename)
        if not os.path.isfile(full_path):
            continue
        assets.append(
            {
                "filename": filename,
                "path": full_path,
                "url": url_for("static", filename=f"uploads/reports/{report_id}/screenshots/{filename}"),
            }
        )
    return assets


def _build_report_pdf(report):
    """Generate a printable PDF summary of a report."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4
    margin = 18 * mm
    y = page_height - margin
    line_height = 13

    def draw_line(text="", bold=False, size=10, spacer=False):
        nonlocal y
        if spacer:
            # Avoid ending a page with negative spacing pushes.
            if y - line_height <= margin:
                pdf.showPage()
                y = page_height - margin
            y -= line_height
            return
        # Break early so the current line never prints inside the bottom margin.
        if y - line_height <= margin:
            pdf.showPage()
            y = page_height - margin
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(margin, y, text)
        y -= line_height

    def draw_block(title, value):
        draw_line(title, bold=True)
        body = _strip_html(value).strip() or "N/A"
        for paragraph in body.splitlines() or ["N/A"]:
            wrapped = textwrap.wrap(paragraph, width=105) or [""]
            for line in wrapped:
                draw_line(line)
        draw_line(spacer=True)

    patient = report.study.patient
    draw_line("MCH PACS - Radiology Report", bold=True, size=14)
    draw_line(spacer=True)
    draw_line(f"Report ID: {report.id}")
    draw_line(f"Status: {(report.status or 'unknown').upper()}")
    draw_line(f"Radiologist: {report.radiologist_name or 'N/A'}")
    draw_line(f"Created (CAT): {_format_cat_time(report.created_at)}")
    draw_line(f"Finalized (CAT): {_format_cat_time(report.finalized_at)}")
    draw_line(f"Signed (CAT): {_format_cat_time(report.signed_at)}")
    draw_line(spacer=True)
    draw_line("Patient Details", bold=True)
    draw_line(f"Patient ID: {patient.patient_id}")
    draw_line(f"Patient Name: {patient.patient_name or 'N/A'}")
    draw_line(f"Sex: {patient.patient_sex or 'N/A'}")
    draw_line(f"DOB: {patient.patient_dob or 'N/A'}")
    draw_line(spacer=True)
    draw_line("Study Details", bold=True)
    draw_line(f"Study UID: {report.study.study_instance_uid}")
    draw_line(f"Study Date: {report.study.study_date or 'N/A'}")
    draw_line(f"Description: {report.study.description or 'N/A'}")
    draw_line(spacer=True)
    draw_block("Findings", report.findings)
    draw_block("Impression", report.impression)
    draw_block("Recommendations", report.recommendations)

    screenshots = _report_screenshot_assets(report.id)
    if screenshots:
        img_margin = 10 * mm
        header_gap = 6
        for index, screenshot in enumerate(screenshots, start=1):
            pdf.showPage()
            title_y = page_height - img_margin
            pdf.setFont("Helvetica-Bold", 12)
            pdf.drawString(img_margin, title_y, f"Image Appendix {index}/{len(screenshots)}")
            pdf.setFont("Helvetica", 9)
            pdf.drawString(img_margin, title_y - 12, screenshot["filename"])

            image_top = title_y - 12 - header_gap
            available_width = page_width - (img_margin * 2)
            available_height = image_top - img_margin
            try:
                image_reader = ImageReader(screenshot["path"])
                image_width, image_height = image_reader.getSize()
                scale = min(available_width / image_width, available_height / image_height)
                draw_width = image_width * scale
                draw_height = image_height * scale
                draw_x = (page_width - draw_width) / 2
                draw_y = img_margin + ((available_height - draw_height) / 2)
                pdf.drawImage(
                    image_reader,
                    draw_x,
                    draw_y,
                    width=draw_width,
                    height=draw_height,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception:
                pdf.setFont("Helvetica", 10)
                pdf.drawString(margin, image_top - line_height, "Unable to render this screenshot.")

    pdf.save()
    buffer.seek(0)
    return buffer

# =====================================================
# EXAM ORDERING (for doctors)
# =====================================================

VALID_ORDER_STATUSES = {"pending", "scheduled", "in_progress", "completed", "cancelled"}
ORDER_TRANSITIONS = {
    "pending": {"scheduled", "cancelled"},
    "scheduled": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _set_order_status(order, new_status):
    """Update order status and maintain relevant workflow timestamps."""
    now_utc = datetime.utcnow()
    order.status = new_status
    if new_status == "scheduled" and not order.scheduled_date:
        order.scheduled_date = now_utc
    if new_status == "completed":
        order.completed_date = now_utc


@ris_bp.route("/orders", methods=["GET"])
@login_required
def list_orders():
    """View all exam orders"""
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    priority = (request.args.get("priority") or "").strip()

    query = ExamOrder.query.join(Patient)

    if q:
        query = query.filter(
            or_(
                ExamOrder.order_number.ilike(f"%{q}%"),
                Patient.patient_id.ilike(f"%{q}%"),
                Patient.patient_name.ilike(f"%{q}%"),
                ExamOrder.ordering_doctor_name.ilike(f"%{q}%"),
                ExamOrder.exam_type.ilike(f"%{q}%"),
                ExamOrder.body_part.ilike(f"%{q}%"),
            )
        )

    if status in VALID_ORDER_STATUSES:
        query = query.filter(ExamOrder.status == status)

    if priority in {"routine", "urgent", "stat"}:
        query = query.filter(ExamOrder.priority == priority)

    orders = query.order_by(ExamOrder.order_date.desc()).all()
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

        log_activity(
            "order_created",
            resource=f"order_{order.id}",
            details=(
                f"{order.order_number} for patient {patient.patient_id} "
                f"({order.exam_type or 'N/A'} {order.body_part or 'N/A'})"
            ),
        )
        
        flash(f"Exam order {order_number} created successfully!", "success")
        return redirect(url_for("ris_bp.list_orders"))
    
    # GET request - show form
    return render_template("ris/order_form.html", patient=patient)


@ris_bp.route("/orders/<int:order_id>", methods=["GET"])
@login_required
def view_order(order_id):
    """View single exam order details"""
    order = ExamOrder.query.get_or_404(order_id)
    log_activity(
        "order_viewed",
        resource=f"order_{order.id}",
        details=f"Viewed order {order.order_number}",
    )
    return render_template("ris/order_detail.html", order=order)


@ris_bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id):
    """Cancel an exam order"""
    order = ExamOrder.query.get_or_404(order_id)
    if order.status in {"completed", "cancelled"}:
        flash(f"Order {order.order_number} cannot be cancelled from status {order.status}", "error")
        return redirect(url_for("ris_bp.view_order", order_id=order.id))
    old_status = order.status
    _set_order_status(order, "cancelled")
    db.session.commit()

    log_activity(
        "order_cancelled",
        resource=f"order_{order.id}",
        details=f"{order.order_number}: {old_status} -> cancelled",
    )
    
    flash(f"Order {order.order_number} cancelled", "info")
    return redirect(url_for("ris_bp.list_orders"))


@ris_bp.route("/orders/<int:order_id>/delete", methods=["POST"])
@login_required
def delete_order(order_id):
    """Hard-delete order (admin only, cancelled-only) for controlled cleanup."""
    if session.get("role") != "admin":
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403

    order = ExamOrder.query.get_or_404(order_id)
    if order.status != "cancelled":
        flash("Only cancelled orders can be deleted", "error")
        return redirect(url_for("ris_bp.view_order", order_id=order.id))
    if order.appointments:
        flash("Order has linked appointments and cannot be deleted", "error")
        return redirect(url_for("ris_bp.view_order", order_id=order.id))
    if order.report:
        flash("Order has linked reports and cannot be deleted", "error")
        return redirect(url_for("ris_bp.view_order", order_id=order.id))

    order_number = order.order_number
    db.session.delete(order)
    db.session.commit()

    log_activity(
        "order_deleted",
        resource=f"order_{order_id}",
        details=f"Deleted cancelled order {order_number}",
    )
    flash(f"Order {order_number} deleted", "success")
    return redirect(url_for("ris_bp.list_orders"))


@ris_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
def update_order_status(order_id):
    """Update order workflow status with transition validation."""
    order = ExamOrder.query.get_or_404(order_id)
    new_status = (request.form.get("status") or "").strip()

    if new_status not in VALID_ORDER_STATUSES:
        flash("Invalid order status", "error")
        return redirect(request.referrer or url_for("ris_bp.view_order", order_id=order.id))

    if new_status not in ORDER_TRANSITIONS.get(order.status, set()):
        flash(f"Invalid transition from {order.status} to {new_status}", "error")
        return redirect(request.referrer or url_for("ris_bp.view_order", order_id=order.id))

    old_status = order.status
    _set_order_status(order, new_status)
    db.session.commit()

    log_activity(
        "order_status_updated",
        resource=f"order_{order.id}",
        details=f"{order.order_number}: {old_status} -> {new_status}",
    )
    flash(f"Order {order.order_number} updated to {new_status}", "success")
    return redirect(request.referrer or url_for("ris_bp.view_order", order_id=order.id))


# =====================================================
# WORKLIST (for radiologists and technicians)
# =====================================================

@ris_bp.route("/worklist", methods=["GET"])
@login_required
def worklist():
    """View pending studies needing reports"""
    # Get filters
    ward_id = request.args.get("ward_id", type=int)
    modality = request.args.get("modality")
    search_query = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    
    # Base query - orders that are completed but don't have reports yet
    from models import Study, RadiologyReport, Instance
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload, selectinload
    
    query = (
        Study.query.options(
            joinedload(Study.patient).joinedload(Patient.ward),
            selectinload(Study.series),
        )
        .join(Patient)
        .outerjoin(RadiologyReport, Study.id == RadiologyReport.study_id_fk)
        .filter(RadiologyReport.id.is_(None))  # No report yet
    )
    
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

    query = query.distinct().order_by(Study.study_date.desc().nullslast(), Study.id.desc())

    studies = query.paginate(page=page, per_page=per_page, error_out=False)
    wards = Ward.query.all()

    # Avoid N+1 loading instances just to compute per-study counts.
    instance_counts = {}
    if studies.items:
        study_ids = [study.id for study in studies.items]
        rows = (
            db.session.query(Study.id, func.count(Instance.id))
            .join(Series, Series.study_key_fk == Study.id)
            .join(Instance, Instance.series_id_fk == Series.id)
            .filter(Study.id.in_(study_ids))
            .group_by(Study.id)
            .all()
        )
        instance_counts = {study_id: count for study_id, count in rows}
    
    return render_template(
        "ris/worklist.html",
        studies=studies,
        wards=wards,
        q=search_query,
        instance_counts=instance_counts,
    )

# =====================================================
# REPORTING (for radiologists)
# =====================================================

@ris_bp.route("/reports/drafts", methods=["GET"])
@login_required
def list_draft_reports():
    """List draft reports for follow-up/editing."""
    from models import Study, RadiologyReport

    search_query = (request.args.get("q") or "").strip()

    query = (
        db.session.query(RadiologyReport)
        .join(Study, RadiologyReport.study_id_fk == Study.id)
        .join(Patient, Study.patient_id_fk == Patient.id)
        .filter(RadiologyReport.status == "draft")
    )

    # Admin can see all drafts; other users see their own drafts.
    if session.get("role") != "admin":
        query = query.filter(RadiologyReport.radiologist_id == session.get("user_id"))

    if search_query:
        query = query.filter(
            or_(
                Patient.patient_id.ilike(f"%{search_query}%"),
                Patient.patient_name.ilike(f"%{search_query}%"),
                Study.study_instance_uid.ilike(f"%{search_query}%"),
                Study.description.ilike(f"%{search_query}%"),
                RadiologyReport.radiologist_name.ilike(f"%{search_query}%"),
            )
        )

    drafts = query.order_by(RadiologyReport.created_at.desc()).all()
    return render_template("ris/draft_reports.html", drafts=drafts)


@ris_bp.route("/reports/saved", methods=["GET"])
@login_required
def list_saved_reports():
    """List saved reports (final/signed by default)."""
    from models import Study

    search_query = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip().lower()
    valid_statuses = {"draft", "final", "signed", "all"}

    query = (
        db.session.query(RadiologyReport)
        .join(Study, RadiologyReport.study_id_fk == Study.id)
        .join(Patient, Study.patient_id_fk == Patient.id)
    )

    if session.get("role") != "admin":
        query = query.filter(RadiologyReport.radiologist_id == session.get("user_id"))

    if status_filter in {"draft", "final", "signed"}:
        query = query.filter(RadiologyReport.status == status_filter)
    elif status_filter != "all":
        query = query.filter(RadiologyReport.status.in_(["final", "signed"]))
        status_filter = "non_draft"

    if search_query:
        query = query.filter(
            or_(
                Patient.patient_id.ilike(f"%{search_query}%"),
                Patient.patient_name.ilike(f"%{search_query}%"),
                Study.study_instance_uid.ilike(f"%{search_query}%"),
                Study.description.ilike(f"%{search_query}%"),
                RadiologyReport.radiologist_name.ilike(f"%{search_query}%"),
            )
        )

    reports = query.order_by(RadiologyReport.created_at.desc()).all()
    return render_template(
        "ris/saved_reports.html",
        reports=reports,
        status_filter=status_filter if status_filter in valid_statuses else "non_draft",
    )


@ris_bp.route("/reports/new/<int:study_id>", methods=["GET", "POST"])
@login_required
def create_report(study_id):
    """Create new radiology report for a study"""
    from models import Study, RadiologyReport
    
    study = Study.query.get_or_404(study_id)

    if request.method == "POST":
        report_id = request.form.get("report_id")
        if report_id:
            report = RadiologyReport.query.get_or_404(report_id)
            if report.study_id_fk != study.id:
                return render_template("error.html", message="Report does not match study."), 400
            if not _is_report_accessible(report):
                return render_template("error.html", message="Access denied. Insufficient permissions."), 403

            report.radiologist_name = request.form.get("radiologist_name") or report.radiologist_name
            report.findings = request.form.get("findings")
            report.impression = request.form.get("impression")
            report.recommendations = request.form.get("recommendations")
            report.status = request.form.get("status", "draft")

            if report.status == "final" and not report.finalized_at:
                report.finalized_at = datetime.utcnow()

            db.session.commit()
            log_activity(
                "report_updated",
                resource=f"report_{report.id}",
                details=f"Updated report status to {report.status}",
            )
            flash("Report updated successfully!", "success")
            return redirect(url_for("ris_bp.view_report", report_id=report.id))
    
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
                report.finalized_at = datetime.utcnow()
            
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
            return render_template(
                "ris/report_form.html",
                study=study,
                report=None,
                screenshot_assets=[],
                is_new_report=True,
            ), 500
    
    # GET - show form (create draft immediately so screenshots can be attached)
    existing_report = (
        RadiologyReport.query.filter_by(study_id_fk=study.id)
        .order_by(RadiologyReport.created_at.desc())
        .first()
    )
    if existing_report:
        if not _is_report_accessible(existing_report):
            return render_template("error.html", message="Access denied. Insufficient permissions."), 403
        if existing_report.status == "draft":
            report = existing_report
            return render_template(
                "ris/report_form.html",
                study=study,
                report=report,
                screenshot_assets=_report_screenshot_assets(report.id),
                is_new_report=True,
            )
        return redirect(url_for("ris_bp.view_report", report_id=existing_report.id))

    report = RadiologyReport(
        study_id_fk=study.id,
        radiologist_id=session.get("user_id"),
        radiologist_name=session.get("full_name"),
        findings="",
        impression="",
        recommendations="",
        status="draft",
    )
    db.session.add(report)
    db.session.commit()
    log_activity(
        "report_draft_started",
        resource=f"study_{study.study_instance_uid}",
        details=f"Draft report {report.id} started",
    )
    return render_template(
        "ris/report_form.html",
        study=study,
        report=report,
        screenshot_assets=_report_screenshot_assets(report.id),
        is_new_report=True,
    )


@ris_bp.route("/reports/<int:report_id>", methods=["GET"])
@login_required
def view_report(report_id):
    """View a radiology report"""
    from models import RadiologyReport
    
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403
    log_activity(
        "report_viewed",
        resource=f"report_{report.id}",
        details=f"Viewed report for study {report.study.study_instance_uid}"
    )
    return render_template(
        "ris/report_view.html",
        report=report,
        screenshot_assets=_report_screenshot_assets(report.id),
    )


@ris_bp.route("/reports/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def edit_report(report_id):
    """Edit an existing report"""
    from models import RadiologyReport
    
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403
    
    if request.method == "POST":
        report.findings = request.form.get("findings")
        report.impression = request.form.get("impression")
        report.recommendations = request.form.get("recommendations")
        report.status = request.form.get("status", "draft")
        
        if report.status == "final" and not report.finalized_at:
            report.finalized_at = datetime.utcnow()
        
        db.session.commit()
        log_activity(
            "report_updated",
            resource=f"report_{report.id}",
            details=f"Updated report status to {report.status}"
        )
        flash("Report updated successfully!", "success")
        return redirect(url_for("ris_bp.view_report", report_id=report.id))
    
    return render_template(
        "ris/report_form.html",
        study=report.study,
        report=report,
        screenshot_assets=_report_screenshot_assets(report.id),
    )


@ris_bp.route("/reports/<int:report_id>/screenshots", methods=["POST"])
@login_required
def upload_report_screenshot(report_id):
    """Attach screenshot evidence to a report."""
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403

    screenshot = request.files.get("screenshot")
    if not screenshot or not screenshot.filename:
        flash("Please choose an image screenshot to upload.", "error")
        return redirect(url_for("ris_bp.edit_report", report_id=report.id))

    original_name = secure_filename(screenshot.filename)
    if not _is_allowed_screenshot(original_name):
        flash("Unsupported screenshot format. Use PNG, JPG, JPEG, or WEBP.", "error")
        return redirect(url_for("ris_bp.edit_report", report_id=report.id))

    extension = original_name.rsplit(".", 1)[1].lower()
    target_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}.{extension}"
    target_dir = _report_screenshot_dir(report.id)
    os.makedirs(target_dir, exist_ok=True)
    screenshot.save(os.path.join(target_dir, target_name))

    log_activity(
        "report_screenshot_added",
        resource=f"report_{report.id}",
        details=f"Attached screenshot {target_name}",
    )

    # XHR upload from clipboard paste flow.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "filename": target_name}), 200

    flash("Screenshot attached to report.", "success")
    next_url = request.args.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("ris_bp.edit_report", report_id=report.id))


@ris_bp.route("/reports/<int:report_id>/screenshots/<path:filename>/delete", methods=["POST"])
@login_required
def delete_report_screenshot(report_id, filename):
    """Remove screenshot evidence from a report."""
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403

    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        flash("Invalid screenshot reference.", "error")
        return redirect(url_for("ris_bp.edit_report", report_id=report.id))

    screenshot_path = os.path.join(_report_screenshot_dir(report.id), safe_name)
    if not os.path.isfile(screenshot_path):
        flash("Screenshot not found.", "error")
        return redirect(url_for("ris_bp.edit_report", report_id=report.id))

    os.remove(screenshot_path)
    log_activity(
        "report_screenshot_deleted",
        resource=f"report_{report.id}",
        details=f"Removed screenshot {safe_name}",
    )
    flash("Screenshot removed.", "info")
    next_url = request.args.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("ris_bp.edit_report", report_id=report.id))


@ris_bp.route("/reports/<int:report_id>/delete", methods=["POST"])
@login_required
def delete_report(report_id):
    """Delete a radiology report and its screenshots."""
    if session.get("role") != "admin":
        return render_template("error.html", message="Access denied. Admins only."), 403
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403

    report_ref = report.id
    study_uid = report.study.study_instance_uid if report.study else "unknown"

    try:
        screenshot_dir = _report_screenshot_dir(report.id)
        if os.path.isdir(screenshot_dir):
            shutil.rmtree(screenshot_dir)

        db.session.delete(report)
        db.session.commit()

        log_activity(
            "report_deleted",
            resource=f"report_{report_ref}",
            details=f"Deleted report for study {study_uid}",
        )
        flash("Report deleted successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete report %s", report_ref)
        flash(f"Failed to delete report: {exc}", "error")

    return redirect(url_for("ris_bp.list_saved_reports"))


@ris_bp.route("/reports/<int:report_id>/pdf", methods=["GET"])
@login_required
def download_report_pdf(report_id):
    """Download report content as PDF."""
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403

    pdf_buffer = _build_report_pdf(report)
    patient_id = report.study.patient.patient_id or "patient"
    filename = f"report_{report.id}_{patient_id}.pdf"

    log_activity(
        "report_pdf_downloaded",
        resource=f"report_{report.id}",
        details=f"Downloaded PDF for study {report.study.study_instance_uid}",
    )

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@ris_bp.route("/reports/<int:report_id>/pdf/view", methods=["GET"])
@login_required
def view_report_pdf(report_id):
    """View report PDF inline (useful for printing without browser URL headers/footers)."""
    report = RadiologyReport.query.get_or_404(report_id)
    if not _is_report_accessible(report):
        return render_template("error.html", message="Access denied. Insufficient permissions."), 403

    pdf_buffer = _build_report_pdf(report)
    patient_id = report.study.patient.patient_id or "patient"
    filename = f"report_{report.id}_{patient_id}.pdf"

    log_activity(
        "report_pdf_viewed",
        resource=f"report_{report.id}",
        details=f"Viewed PDF for study {report.study.study_instance_uid}",
    )

    return send_file(
        pdf_buffer,
        as_attachment=False,
        download_name=filename,
        mimetype="application/pdf",
    )



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
    patients = Patient.query.order_by(Patient.patient_id.asc()).all()
    open_orders = (
        ExamOrder.query
        .filter(ExamOrder.status.in_(["pending", "scheduled"]))
        .order_by(ExamOrder.order_date.desc())
        .all()
    )
    return render_template(
        "ris/schedule_board.html",
        appointments=appointments,
        patients=patients,
        open_orders=open_orders,
        selected_order_id=request.args.get("order_id", type=int),
    )

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
            _set_order_status(order, "scheduled")
            order.scheduled_date = start_dt

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


@ris_bp.route("/schedule/<int:appointment_id>/delete", methods=["POST"])
@login_required
def delete_appointment(appointment_id):
    """Delete completed appointments from schedule board."""
    appt = Appointment.query.get_or_404(appointment_id)
    if appt.status != "completed":
        flash("Only completed appointments can be deleted", "error")
        return redirect(url_for("ris_bp.schedule_board"))

    appt_info = f"id={appt.id}, patient={appt.patient_id_fk}, modality={appt.modality}, start={appt.scheduled_start}"
    db.session.delete(appt)
    db.session.commit()

    log_activity(
        "appointment_deleted",
        resource=f"appointment_{appointment_id}",
        details=appt_info
    )

    flash("Completed appointment deleted", "success")
    return redirect(url_for("ris_bp.schedule_board"))
