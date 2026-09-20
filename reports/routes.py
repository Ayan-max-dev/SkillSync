from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from models import Comment, Notification, Offer, Report, Request as LearningRequest, Session, User, db


reports_bp = Blueprint("reports", __name__)

REPORT_TYPES = {"offer", "request", "comment", "recording"}
REPORT_REASONS = {
    "Inappropriate or unsafe content",
    "Harassment or bullying",
    "Spam or misleading content",
    "Other",
}


def _get_target(target_type, target_id):
    if target_type == "offer":
        return Offer.query.get_or_404(target_id)
    if target_type == "request":
        return LearningRequest.query.get_or_404(target_id)
    if target_type == "comment":
        return Comment.query.get_or_404(target_id)
    if target_type == "recording":
        session = Session.query.get_or_404(target_id)
        if not session.recording_url:
            return None
        return session
    return None


def _target_label(target_type, target):
    if target_type == "offer":
        return f"Offer: {target.title}"
    if target_type == "request":
        return f"Request: {target.skill.name}"
    if target_type == "comment":
        return f"Comment on: {target.offer.title}"
    return f"Recording for: {target.offer.title}"


def _target_key(target_type, target_id):
    return f"{target_type}:{target_id}"


def _redirect_after_report(target_type, target):
    if target_type == "offer":
        return redirect(url_for("offers.offer_detail", offer_id=target.id))
    if target_type == "comment":
        return redirect(url_for("offers.offer_detail", offer_id=target.offer_id))
    if target_type == "recording":
        return redirect(url_for("offers.offer_detail", offer_id=target.offer_id))
    return redirect(url_for("main.explore"))


@reports_bp.route("/reports/new", methods=["GET", "POST"])
@login_required
def new_report():
    target_type = request.values.get("target_type", "").strip().lower()
    target_id = request.values.get("target_id", type=int)

    if target_type not in REPORT_TYPES or not target_id:
        flash("That content cannot be reported.")
        return redirect(url_for("main.explore"))

    target = _get_target(target_type, target_id)
    if target is None:
        flash("That recording is no longer available to report.")
        return redirect(url_for("main.explore"))

    if request.method == "POST":
        reason_type = (request.form.get("reason_type") or "").strip()
        details = (request.form.get("details") or "").strip()

        if reason_type not in REPORT_REASONS:
            flash("Choose a report reason.")
            return render_template("new_report.html", target=target, target_type=target_type, target_label=_target_label(target_type, target), report_reasons=sorted(REPORT_REASONS))
        if len(details) > 1000:
            flash("Additional details must be 1,000 characters or fewer.")
            return render_template("new_report.html", target=target, target_type=target_type, target_label=_target_label(target_type, target), report_reasons=sorted(REPORT_REASONS))

        reason = reason_type if not details else f"{reason_type}: {details}"
        report = Report(
            reporter_id=current_user.id,
            target_key=_target_key(target_type, target.id),
            reason=reason,
        )
        setattr(report, f"{target_type if target_type != 'recording' else 'session'}_id", target.id)
        db.session.add(report)

        try:
            db.session.flush()
            admins = User.query.filter_by(is_admin=True).all()
            message = f"New report: {_target_label(target_type, target)}"
            link = url_for("admin.report_detail", report_id=report.id)
            for admin in admins:
                db.session.add(Notification(
                    user_id=admin.id,
                    category="moderation",
                    message=message,
                    link=link,
                ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("You've already reported this content.")
            return _redirect_after_report(target_type, target)

        flash("Report submitted. The content will remain visible until an administrator reviews it.")
        return _redirect_after_report(target_type, target)

    return render_template(
        "new_report.html",
        target=target,
        target_type=target_type,
        target_label=_target_label(target_type, target),
        report_reasons=sorted(REPORT_REASONS),
    )
