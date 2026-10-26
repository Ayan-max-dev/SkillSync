from datetime import datetime
from io import BytesIO
from pathlib import Path
import secrets

import qrcode
from PIL import Image
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

    teal = colors.HexColor("#063F3A")
    teal_dark = colors.HexColor("#032F2C")
    teal_soft = colors.HexColor("#E6F0EC")
    gold = colors.HexColor("#C8942E")
    muted = colors.HexColor("#28555A")
    paper = colors.HexColor("#FCFBF5")
    ink = colors.HexColor("#073D39")

    # Deep outer frame and restrained diagonal corner accents match the reference.
    pdf.setFillColor(teal_dark)
    pdf.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    pdf.setFillColor(paper)
    pdf.rect(14, 14, page_w - 28, page_h - 28, fill=1, stroke=0)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.3)
    pdf.rect(22, 22, page_w - 44, page_h - 44, fill=0, stroke=1)
    pdf.setStrokeColor(colors.HexColor("#E4D7B3"))
    pdf.setLineWidth(0.6)
    pdf.rect(28, 28, page_w - 56, page_h - 56, fill=0, stroke=1)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(2)
    pdf.line(0, page_h - 48, 73, page_h)
    pdf.line(page_w - 73, 0, page_w, 48)
    pdf.line(0, 48, 30, 78)
    pdf.line(page_w - 30, page_h - 78, page_w, page_h - 48)

    # A very faint botanical watermark adds depth without competing with the content.
    try:
        pdf.setFillAlpha(0.055)
        pdf.setStrokeAlpha(0.055)
    except AttributeError:
        pass
    pdf.setFillColor(teal)
    pdf.setStrokeColor(teal)
    stem = pdf.beginPath()
    stem.moveTo(page_w - 178, 92)
    stem.curveTo(page_w - 145, 172, page_w - 133, 264, page_w - 66, 405)
    pdf.drawPath(stem, stroke=1, fill=0)
    for leaf_x, leaf_y, leaf_w, leaf_h in (
        (page_w - 180, 160, 72, 30),
        (page_w - 188, 220, 82, 34),
        (page_w - 145, 280, 72, 30),
        (page_w - 105, 342, 62, 27),
    ):
        leaf = pdf.beginPath()
        leaf.moveTo(leaf_x, leaf_y)
        leaf.curveTo(
            leaf_x + leaf_w * 0.25, leaf_y + leaf_h,
            leaf_x + leaf_w * 0.78, leaf_y + leaf_h,
            leaf_x + leaf_w, leaf_y + leaf_h * 0.35,
        )
        leaf.curveTo(
            leaf_x + leaf_w * 0.64, leaf_y - leaf_h * 0.05,
            leaf_x + leaf_w * 0.25, leaf_y - leaf_h * 0.02,
            leaf_x, leaf_y,
        )
        pdf.drawPath(leaf, stroke=0, fill=1)
    try:
        pdf.setFillAlpha(1)
        pdf.setStrokeAlpha(1)
    except AttributeError:
        pass

    # Remove the supplied PNG's white matte while preserving its original artwork.
    logo_path = Path(current_app.root_path) / "static" / "school-logo.png"
    if logo_path.is_file():
        logo_image = Image.open(logo_path).convert("RGBA")
        pixels = logo_image.load()
        for y in range(logo_image.height):
            for x in range(logo_image.width):
                r, g, b, alpha = pixels[x, y]
                if r > 242 and g > 242 and b > 242:
                    pixels[x, y] = (r, g, b, 0)
        logo_buffer = BytesIO()
        logo_image.save(logo_buffer, format="PNG")
        logo_buffer.seek(0)
        logo = ImageReader(logo_buffer)
        logo_w, logo_h = logo.getSize()
        max_logo_w, max_logo_h = 92, 102
        scale = min(max_logo_w / logo_w, max_logo_h / logo_h)
        draw_w, draw_h = logo_w * scale, logo_h * scale
        pdf.drawImage(
            logo,
            45,
            page_h - 42 - draw_h,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )

    pdf.setFillColor(teal)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawRightString(page_w - 48, page_h - 55, "SkillSync")
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(page_w - 48, page_h - 70, "PEER-TO-PEER LEARNING")

    # QR verification remains generated from the certificate's real verification URL.
    verify_url = url_for("certificates.verify_certificate", code=certificate.certificate_code, _external=True)
    qr_img = qrcode.make(verify_url)
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    qr_size = 62
    qr_x = page_w - 52 - qr_size
    qr_y = page_h - 163
    pdf.setFillColor(colors.white)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.1)
    pdf.roundRect(qr_x - 7, qr_y - 7, qr_size + 14, qr_size + 14, 6, fill=1, stroke=1)
    pdf.drawImage(ImageReader(qr_buffer), qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")
    pdf.setFillColor(teal)
    pdf.setFont("Helvetica-Bold", 6.2)
    pdf.drawCentredString(qr_x + qr_size / 2, qr_y - 17, "SCAN TO VERIFY")
    pdf.setFont("Helvetica", 6.2)
    pdf.drawCentredString(qr_x + qr_size / 2, qr_y - 27, certificate.certificate_code)

    center_x = page_w / 2
    # The community label stands alone so decorative lines cannot cross its letters.
    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(center_x, page_h - 94, "S K I L L S Y N C   C O M M U N I T Y")
    pdf.setFillColor(teal)
    pdf.setFont("Times-Bold", 34)
    pdf.drawCentredString(center_x, page_h - 145, "Certificate of Contribution")
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1)
    pdf.line(center_x - 82, page_h - 172, center_x - 25, page_h - 172)
    pdf.line(center_x + 25, page_h - 172, center_x + 82, page_h - 172)
    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(center_x, page_h - 176, "◆")
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(center_x, page_h - 207, "P R E S E N T E D   T O")
    pdf.setFillColor(ink)
    pdf.setFont("Times-Bold", 39)
    pdf.drawCentredString(center_x, page_h - 255, teacher.name[:55])
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(center_x, page_h - 285, "for sharing knowledge through a peer-learning session")

    topic = f"{offer.skill.name}  ·  {offer.title}"
    if len(topic) > 75:
        topic = topic[:72] + "..."
    pdf.setFillColor(teal)
    pdf.setFont("Times-Bold", 20)
    pdf.drawCentredString(center_x, page_h - 330, topic)

    # The metadata strip uses circular pictograms like the reference.
    band_x, band_y, band_w, band_h = 39, 78, page_w - 78, 82
    pdf.setFillColor(teal_soft)
    pdf.roundRect(band_x, band_y, band_w, band_h, 10, fill=1, stroke=0)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(0.8)
    pdf.roundRect(band_x, band_y, band_w, band_h, 10, fill=0, stroke=1)

    date_text = session.start_time.strftime("%d %B %Y")
    duration_hours = None
    if session.start_time and session.end_time and session.end_time > session.start_time:
        duration_hours = (session.end_time - session.start_time).total_seconds() / 3600
    duration_text = f"{duration_hours:g} hours" if duration_hours is not None else "Not recorded"
    metadata = [
        ("SESSION DATE", date_text),
        ("SESSION DURATION", duration_text),
        ("CERTIFICATE ID", certificate.certificate_code),
    ]
    column_w = band_w / len(metadata)
    for index, (label, value) in enumerate(metadata):
        x = band_x + column_w * index + 70
        if index:
            pdf.setStrokeColor(colors.HexColor("#B7C7BC"))
            pdf.line(band_x + column_w * index, band_y + 15, band_x + column_w * index, band_y + band_h - 15)
        icon_x, icon_y = band_x + column_w * index + 42, band_y + band_h / 2
        pdf.setFillColor(teal)
        pdf.circle(icon_x, icon_y, 15, fill=1, stroke=0)
        pdf.setStrokeColor(colors.white)
        pdf.setLineWidth(1.2)
        if index == 0:
            pdf.rect(icon_x - 7, icon_y - 6, 14, 12, fill=0, stroke=1)
            pdf.line(icon_x - 4, icon_y + 9, icon_x - 4, icon_y + 5)
            pdf.line(icon_x + 4, icon_y + 9, icon_x + 4, icon_y + 5)
        elif index == 1:
            pdf.circle(icon_x, icon_y, 7, fill=0, stroke=1)
            pdf.line(icon_x, icon_y, icon_x, icon_y + 4)
            pdf.line(icon_x, icon_y, icon_x + 3, icon_y - 2)
        else:
            pdf.circle(icon_x, icon_y, 7, fill=0, stroke=1)
            pdf.line(icon_x - 4, icon_y - 3, icon_x, icon_y - 7)
            pdf.line(icon_x, icon_y - 7, icon_x + 5, icon_y + 2)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(x, band_y + 49, label)
        pdf.setFillColor(teal)
        pdf.setFont("Times-Bold", 12)
        pdf.drawString(x, band_y + 28, value[:28])

    pdf.setFillColor(muted)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(0.8)
    pdf.line(center_x - 80, 57, center_x - 20, 57)
    pdf.line(center_x + 20, 57, center_x + 80, 57)
    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(center_x, 54, "◆")
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 7.5)
    pdf.drawCentredString(center_x, 38, "This certificate recognizes a documented contribution to the SkillSync learning community.")
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
    response = send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"SkillSync-Modern-Certificate-{safe_code}.pdf",
        max_age=0,
        conditional=False,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Certificate-Design"] = "teal-cream-v2"
    return response


@certificates_bp.route("/verify/<code>")
def verify_certificate(code):
    certificate = Certificate.query.filter_by(certificate_code=code).first_or_404()
    return render_template("certificate_verify.html", certificate=certificate, valid=certificate.revoked_at is None)
