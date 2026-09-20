from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload

from models import Offer, Report, Request as LearningRequest, User, db


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not current_user.is_admin:
        abort(403)


def _hide_target(report):
    if report.offer:
        report.offer.status = "hidden"
    elif report.request:
        report.request.status = "hidden"
    elif report.comment:
        report.comment.hidden = True
    elif report.session:
        report.session.recording_hidden = True
    else:
        return False
    return True


def _restore_target(report):
    if report.offer:
        report.offer.status = "open"
    elif report.request:
        report.request.status = "open"
    elif report.comment:
        report.comment.hidden = False
    elif report.session:
        report.session.recording_hidden = False
    else:
        return False
    return True


@admin_bp.route("/")
@admin_bp.route("/dashboard")
def dashboard():
    status_filter = request.args.get("status", "open")
    if status_filter not in {"open", "resolved", "dismissed", "restored", "all"}:
        status_filter = "open"

    reports_query = Report.query.options(selectinload(Report.reporter)).order_by(Report.created_at.desc())
    if status_filter != "all":
        reports_query = reports_query.filter_by(status=status_filter)

    reports = reports_query.all()
    users = User.query.order_by(User.name.asc()).all()
    offers = (
        Offer.query
        .options(selectinload(Offer.teacher))
        .order_by(Offer.id.desc())
        .all()
    )
    requests = (
        LearningRequest.query
        .options(selectinload(LearningRequest.student))
        .order_by(LearningRequest.id.desc())
        .all()
    )

    return render_template(
        "admin_dashboard.html",
        reports=reports,
        users=users,
        offers=offers,
        requests=requests,
        status_filter=status_filter,
    )


@admin_bp.route("/users/<int:user_id>/promote", methods=["POST"])
def promote_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash(f"{user.name} is already an admin.")
        return redirect(url_for("admin.dashboard"))

    user.is_admin = True
    db.session.commit()
    flash(f"{user.name} is now an admin.")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/reports/<int:report_id>")
def report_detail(report_id):
    report = Report.query.get_or_404(report_id)
    return render_template("admin_report_detail.html", report=report)


@admin_bp.route("/reports/<int:report_id>/resolve", methods=["POST"])
def resolve_report(report_id):
    report = Report.query.get_or_404(report_id)
    if report.status != "open":
        flash("This report has already been reviewed.")
        return redirect(url_for("admin.report_detail", report_id=report.id))

    action = request.form.get("action")
    note = (request.form.get("resolution_note") or "").strip()
    if len(note) > 1000:
        flash("Resolution note must be 1,000 characters or fewer.")
        return redirect(url_for("admin.report_detail", report_id=report.id))

    if action == "hide":
        if not _hide_target(report):
            flash("The reported content no longer exists.")
            return redirect(url_for("admin.report_detail", report_id=report.id))

        now = datetime.now()
        open_reports = Report.query.filter_by(target_key=report.target_key, status="open").all()
        for item in open_reports:
            item.status = "resolved"
            item.resolved_by_id = current_user.id
            item.resolved_at = now
            item.resolution_note = note or "Content hidden by an administrator."
        db.session.commit()
        flash("Reported content was hidden and its open reports were resolved.")

    elif action == "dismiss":
        report.status = "dismissed"
        report.resolved_by_id = current_user.id
        report.resolved_at = datetime.now()
        report.resolution_note = note or "Report dismissed after review."
        db.session.commit()
        flash("Report dismissed.")

    else:
        flash("Choose a valid moderation action.")

    return redirect(url_for("admin.report_detail", report_id=report.id))


@admin_bp.route("/reports/<int:report_id>/restore", methods=["POST"])
def restore_report(report_id):
    report = Report.query.get_or_404(report_id)
    if report.status != "resolved":
        flash("Only hidden content can be restored.")
        return redirect(url_for("admin.report_detail", report_id=report.id))

    if not _restore_target(report):
        flash("The reported content no longer exists.")
        return redirect(url_for("admin.report_detail", report_id=report.id))

    now = datetime.now()
    hidden_reports = Report.query.filter_by(target_key=report.target_key, status="resolved").all()
    for item in hidden_reports:
        item.status = "restored"
        item.resolved_by_id = current_user.id
        item.resolved_at = now
        previous_note = item.resolution_note or ""
        item.resolution_note = f"{previous_note}\nRestored by {current_user.name} on {now.strftime('%b %d, %Y')}.".strip()
    db.session.commit()
    flash("Content restored and is visible again.")
    return redirect(url_for("admin.report_detail", report_id=report.id))