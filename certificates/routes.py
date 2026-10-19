from datetime import datetime
from io import BytesIO
from pathlib import Path
import secrets

import qrcode
from flask import Blueprint, abort, current_app, flash, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy.exc import IntegrityError

from models import Certificate, Enrollment, Notification, Report, Session, db

certificates_bp = Blueprint("certificates", __name__, url_prefix="/certificates")


def _pdf_for(certificate):
    """Draws text and design directly onto a PDF; values come from DB records."""
    session = certificate.session
    teacher = certificate.recipient
    offer = session.offer
    buffer = BytesIO()
    page_w, page_h = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=(page_w, page_h))

    # Clean blue-and-white certificate design inspired by the supplied sample.
    pdf.setFillColor(colors.HexColor("#F8FBFF"))
    pdf.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#245DB5")); pdf.setLineWidth(2)
    pdf.rect(18, 18, page_w-36, page_h-36, fill=0, stroke=1)
    pdf.setStrokeColor(colors.HexColor("#9DBBEA")); pdf.setLineWidth(0.7)
    pdf.rect(25, 25, page_w-50, page_h-50, fill=0, stroke=1)

    pdf.setFillColor(colors.HexColor("#142B55"))
    pdf.setFont("Helvetica-Bold", 29)
    pdf.drawCentredString(page_w/2, page_h-75, "SkillSync")
    pdf.setFillColor(colors.HexColor("#4B5D7A")); pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(page_w/2, page_h-96, "Student-to-Student Learning Platform")

    pdf.setFillColor(colors.HexColor("#102650")); pdf.setFont("Helvetica-Bold", 23)
    pdf.drawCentredString(page_w/2, page_h-145, "CERTIFICATE OF CONTRIBUTION")
    pdf.setStrokeColor(colors.HexColor("#356BC0")); pdf.setLineWidth(1.5)
    pdf.line(page_w/2-110, page_h-160, page_w/2-30, page_h-160)
    pdf.line(page_w/2+30, page_h-160, page_w/2+110, page_h-160)

    pdf.setFillColor(colors.HexColor("#40516F")); pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(page_w/2, page_h-190, "This certificate is proudly presented to")
    pdf.setFillColor(colors.HexColor("#102650")); pdf.setFont("Helvetica-Bold", 25)
    name = teacher.name[:90]
    pdf.drawCentredString(page_w/2, page_h-225, name)
    pdf.setFillColor(colors.HexColor("#40516F")); pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(page_w/2, page_h-253, "for successfully conducting a peer-learning session on")
    pdf.setFillColor(colors.HexColor("#245DB5")); pdf.setFont("Helvetica-Bold", 16)
    topic = f"{offer.skill.name} — {offer.title}"
    if len(topic) > 75:
        topic = topic[:72] + "..."
    pdf.drawCentredString(page_w/2, page_h-282, topic)

    date_text = session.start_time.strftime("%d %B %Y")
    pdf.setFillColor(colors.HexColor("#142B55")); pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(60, 88, date_text)
    pdf.setFillColor(colors.HexColor("#53627A")); pdf.setFont("Helvetica", 7)
    pdf.drawString(60, 73, "SESSION DATE")
    pdf.setStrokeColor(colors.HexColor("#6B91D3")); pdf.line(210, 65, 210, 108)
    pdf.setFillColor(colors.HexColor("#142B55")); pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(235, 88, certificate.certificate_code)
    pdf.setFillColor(colors.HexColor("#53627A")); pdf.setFont("Helvetica", 7)
    pdf.drawString(235, 73, "CERTIFICATE ID")
    pdf.setStrokeColor(colors.HexColor("#6B91D3")); pdf.line(page_w-220, 65, page_w-220, 108)
    pdf.setFillColor(colors.HexColor("#142B55")); pdf.setFont("Helvetica-Oblique", 14)
    pdf.drawString(page_w-195, 91, "SkillSync Admin")
    pdf.setFillColor(colors.HexColor("#53627A")); pdf.setFont("Helvetica", 7)
    pdf.drawString(page_w-195, 73, "SKILLSYNC PLATFORM ADMIN")

    verify_url = url_for("certificates.verify_certificate", code=certificate.certificate_code, _external=True)
    qr_img = qrcode.make(verify_url)
    qr_buffer = BytesIO(); qr_img.save(qr_buffer, format="PNG"); qr_buffer.seek(0)
    pdf.drawImage(ImageReader(qr_buffer), page_w-105, 54, width=58, height=58, preserveAspectRatio=True, mask="auto")
    pdf.setFillColor(colors.HexColor("#53627A")); pdf.setFont("Helvetica", 6.5)
    pdf.drawCentredString(page_w-76, 44, "SCAN TO VERIFY")
    pdf.setFillColor(colors.HexColor("#245DB5")); pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(page_w/2, 34, "SkillSync")
    pdf.save(); buffer.seek(0)
    return buffer


@certificates_bp.route("/")
@login_required
def my_certificates():
    certificates = Certificate.query.filter_by(recipient_id=current_user.id).order_by(Certificate.issued_at.desc()).all()
    return render_template("certificates.html", certificates=certificates)


@certificates_bp.route("/<int:certificate_id>/download")
@login_required
def download_certificate(certificate_id):
    certificate = Certificate.query.get_or_404(certificate_id)
    if not current_user.is_admin and certificate.recipient_id != current_user.id:
        abort(403)
    if certificate.revoked_at is not None:
        abort(404)
    pdf = _pdf_for(certificate)
    safe_code = "".join(ch for ch in certificate.certificate_code if ch.isalnum() or ch in "-")
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=f"SkillSync-{safe_code}.pdf")


@certificates_bp.route("/verify/<code>")
def verify_certificate(code):
    certificate = Certificate.query.filter_by(certificate_code=code).first_or_404()
    return render_template("certificate_verify.html", certificate=certificate, valid=certificate.revoked_at is None)
