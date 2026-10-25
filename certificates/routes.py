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

    navy = colors.HexColor("#142B55")
    blue = colors.HexColor("#245DB5")
    muted = colors.HexColor("#53627A")
    pale_blue = colors.HexColor("#EAF2FF")
    paper = colors.HexColor("#F8FBFF")

    pdf.setFillColor(paper)
    pdf.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    pdf.setFillColor(navy)
    pdf.rect(0, page_h - 9, page_w, 9, fill=1, stroke=0)
    pdf.rect(0, 0, page_w, 9, fill=1, stroke=0)
    pdf.setStrokeColor(blue); pdf.setLineWidth(1.8)
    pdf.rect(18, 18, page_w - 36, page_h - 36, fill=0, stroke=1)
    pdf.setStrokeColor(colors.HexColor("#A9C4ED")); pdf.setLineWidth(0.7)
    pdf.rect(26, 26, page_w - 52, page_h - 52, fill=0, stroke=1)

    # Small corner accents make the border feel intentional without crowding the content.
    pdf.setFillColor(blue)
    for x, y in ((26, page_h - 31), (page_w - 38, page_h - 31), (26, 26), (page_w - 38, 26)):
        pdf.circle(x, y, 2.5, fill=1, stroke=0)

    pdf.setFillColor(navy)
    pdf.setFont("Helvetica-Bold", 28)
    pdf.drawCentredString(page_w / 2, page_h - 72, "SkillSync")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 9.5)
    pdf.drawCentredString(page_w / 2, page_h - 91, "STUDENT-TO-STUDENT LEARNING PLATFORM")
    pdf.setStrokeColor(colors.HexColor("#B9CDED")); pdf.setLineWidth(0.8)
    pdf.line(page_w / 2 - 75, page_h - 104, page_w / 2 + 75, page_h - 104)

    pdf.setFillColor(navy); pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(page_w / 2, page_h - 141, "CERTIFICATE OF CONTRIBUTION")
    pdf.setStrokeColor(blue); pdf.setLineWidth(1.4)
    pdf.line(page_w / 2 - 116, page_h - 155, page_w / 2 - 36, page_h - 155)
    pdf.line(page_w / 2 + 36, page_h - 155, page_w / 2 + 116, page_h - 155)

    pdf.setFillColor(muted); pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(page_w / 2, page_h - 186, "This certificate is proudly presented to")
    pdf.setFillColor(navy); pdf.setFont("Helvetica-Bold", 25)
    name = teacher.name[:90]
    pdf.drawCentredString(page_w / 2, page_h - 222, name)
    pdf.setStrokeColor(blue); pdf.setLineWidth(1)
    pdf.line(page_w / 2 - 105, page_h - 232, page_w / 2 + 105, page_h - 232)

    pdf.setFillColor(muted); pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(page_w / 2, page_h - 259, "for successfully conducting a peer-learning session on")
    pdf.setFillColor(blue); pdf.setFont("Helvetica-Bold", 16)
    topic = f"{offer.skill.name}  |  {offer.title}"
    if len(topic) > 75:
        topic = topic[:72] + "..."
    pdf.drawCentredString(page_w / 2, page_h - 288, topic)

    # A light information band keeps the metadata grouped and easy to scan.
    pdf.setFillColor(pale_blue)
    pdf.roundRect(48, 116, page_w - 96, 54, 8, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#C1D4F2")); pdf.setLineWidth(0.7)
    pdf.roundRect(48, 116, page_w - 96, 54, 8, fill=0, stroke=1)

    date_text = session.start_time.strftime("%d %B %Y")
    pdf.setFillColor(navy); pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(66, 145, date_text)
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 7)
    pdf.drawString(66, 130, "SESSION DATE")
    pdf.setStrokeColor(colors.HexColor("#8EAFE1")); pdf.line(218, 127, 218, 159)
    pdf.setFillColor(navy); pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(243, 145, certificate.certificate_code)
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 7)
    pdf.drawString(243, 130, "CERTIFICATE ID")

    # Keep the signature and administrator attribution in their own column.
    signature_left = page_w - 287
    signature_right = page_w - 138
    pdf.setStrokeColor(colors.HexColor("#6B91D3")); pdf.setLineWidth(0.8)
    pdf.line(signature_left, 132, signature_right, 132)
    pdf.setFillColor(navy); pdf.setFont("Helvetica-Oblique", 16)
    pdf.drawCentredString((signature_left + signature_right) / 2, 139, "Alex Morgan")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 7)
    pdf.drawCentredString((signature_left + signature_right) / 2, 121, "SKILLSYNC PLATFORM ADMIN")

    verify_url = url_for("certificates.verify_certificate", code=certificate.certificate_code, _external=True)
    qr_img = qrcode.make(verify_url)
    qr_buffer = BytesIO(); qr_img.save(qr_buffer, format="PNG"); qr_buffer.seek(0)
    qr_x = page_w - 104
    pdf.drawImage(ImageReader(qr_buffer), qr_x, 47, width=58, height=58, preserveAspectRatio=True, mask="auto")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 6.5)
    pdf.drawCentredString(qr_x + 29, 37, "SCAN TO VERIFY")
    pdf.setFillColor(blue); pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(page_w / 2, 38, "SkillSync  •  Learn. Share. Grow.")
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
