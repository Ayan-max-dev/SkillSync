from datetime import datetime
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload

from models import Certificate, Enrollment, Offer, Report, Request as LearningRequest, Session, User, Notification, db


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


def _notify_user(user_id, category, message, link=None):
    db.session.add(Notification(user_id=user_id, category=category, message=message, link=link))


@admin_bp.route("/")
@admin_bp.route("/dashboard")
def dashboard():
    status_filter = request.args.get("status", "open")
    if status_filter not in {"open", "resolved", "dismissed", "restored", "all"}:
        status_filter = "open"

    reports_query = Report.query.options(selectinload(Report.reporter)).order_by(Report.created_at.desc())
    if status_filter != "all":
        reports_query = reports_query.filter_by(status=status_filter)

    reports_page = reports_query.paginate(page=request.args.get("reports_page", 1, type=int), per_page=20, error_out=False)
    users_page = User.query.order_by(User.name.asc()).paginate(page=request.args.get("users_page", 1, type=int), per_page=20, error_out=False)
    offers = Offer.query.options(selectinload(Offer.teacher)).order_by(Offer.id.desc()).all()
    requests_page = LearningRequest.query.options(selectinload(LearningRequest.student)).order_by(LearningRequest.id.desc()).paginate(page=request.args.get("requests_page", 1, type=int), per_page=20, error_out=False)
    pending_offers_page = Offer.query.filter(Offer.approval_status == "pending").order_by(Offer.id.desc()).paginate(page=request.args.get("offers_page", 1, type=int), per_page=12, error_out=False)
    pending_recordings_page = Session.query.join(Offer).filter(
        Session.recording_approval_status.in_(["submitted", "rejected"]),
        Session.recording_url.isnot(None),
        Session.deleted_at.is_(None),
    ).order_by(Session.end_time.desc()).paginate(page=request.args.get("recordings_page", 1, type=int), per_page=12, error_out=False)
    sessions_page = (
        Session.query
        .join(Offer)
        .filter(~Session.certificate.has())
        .order_by(Session.start_time.desc())
        .paginate(page=request.args.get("sessions_page", 1, type=int), per_page=20, error_out=False)
    )

    return render_template(
        "admin_dashboard.html",
        reports=reports_page, users=users_page, offers=offers, requests=requests_page,
        pending_offers=pending_offers_page, pending_recordings=pending_recordings_page,
        sessions=sessions_page, status_filter=status_filter,
        reports_page=reports_page, users_page=users_page, requests_page=requests_page,
        offers_page=pending_offers_page, recordings_page=pending_recordings_page,
        sessions_page=sessions_page,
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


@admin_bp.route("/offers/<int:offer_id>/review", methods=["POST"])
def review_offer(offer_id):
    offer = Offer.query.get_or_404(offer_id)
    action = request.form.get("action")
    note = (request.form.get("review_note") or "").strip()
    if len(note) > 1000:
        flash("Review note must be 1,000 characters or fewer.")
        return redirect(url_for("admin.dashboard"))
    if action == "approve":
        offer.approval_status = "approved"
        offer.approval_note = None
        offer.status = "open"
        _notify_user(offer.teacher_id, "moderation", f"Your offer '{offer.title}' was approved and is now visible on Explore.", url_for("offers.offer_detail", offer_id=offer.id))
        db.session.commit()
        flash("Offer approved and published.")
    elif action == "reject":
        offer.approval_status = "rejected"
        offer.approval_note = note or "Please revise the offer and resubmit it for review."
        _notify_user(offer.teacher_id, "moderation", f"Your offer '{offer.title}' needs changes before it can be published.", url_for("offers.edit_offer", offer_id=offer.id))
        db.session.commit()
        flash("Offer rejected and returned to the student for changes.")
    else:
        flash("Choose a valid review action.")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/sessions/<int:session_id>/recording-review", methods=["POST"])
def review_recording(session_id):
    target_session = Session.query.get_or_404(session_id)
    action = request.form.get("action")
    note = (request.form.get("review_note") or "").strip()
    if len(note) > 1000:
        flash("Review note must be 1,000 characters or fewer.")
        return redirect(url_for("admin.dashboard"))
    if not target_session.recording_url:
        flash("There is no recording to review.")
        return redirect(url_for("admin.dashboard"))
    if action == "approve":
        target_session.recording_approval_status = "approved"
        target_session.recording_review_note = None
        _notify_user(target_session.offer.teacher_id, "moderation", f"The recording for '{target_session.offer.title}' was approved. The session can now count as completed when attendance is complete.", url_for("offers.offer_detail", offer_id=target_session.offer_id))
        for enrollment in target_session.enrollments:
            if enrollment.status == "confirmed":
                _notify_user(enrollment.student_id, "moderation", f"The recording for '{target_session.offer.title}' was approved and is now available.", url_for("offers.offer_detail", offer_id=target_session.offer_id))
        db.session.commit()
        flash("Recording approved.")
    elif action == "reject":
        target_session.recording_approval_status = "rejected"
        target_session.recording_review_note = note or "Please upload a suitable recording and resubmit it for review."
        _notify_user(target_session.offer.teacher_id, "moderation", f"The recording for '{target_session.offer.title}' needs changes before it can be approved.", url_for("sessions.add_recording", session_id=target_session.id))
        db.session.commit()
        flash("Recording rejected and returned to the teacher.")
    else:
        flash("Choose a valid review action.")
    return redirect(
        url_for("admin.review_session_detail", session_id=session_id)
    )


@admin_bp.route("/sessions/<int:session_id>/reject-completion", methods=["POST"])
def reject_completion(session_id):
    target_session = Session.query.get_or_404(session_id)
    note = (request.form.get("review_note") or "").strip()
    if len(note) > 1000:
        flash("Review note must be 1,000 characters or fewer.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    if not target_session.recording_url:
        flash("There is no recording to review.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))

    target_session.recording_approval_status = "rejected"
    target_session.recording_review_note = (
        note or "The session completion needs changes before it can be approved."
    )
    _notify_user(
        target_session.offer.teacher_id,
        "moderation",
        f"The completion for '{target_session.offer.title}' needs changes before it can be approved.",
        url_for("sessions.add_recording", session_id=target_session.id),
    )
    db.session.commit()
    flash("Session completion rejected and returned to the teacher for changes.")
    return redirect(url_for("admin.review_session_detail", session_id=session_id))


@admin_bp.route("/sessions/<int:session_id>/delete", methods=["POST"])
def delete_session(session_id):
    target_session = Session.query.get_or_404(session_id)
    if target_session.deleted_at is not None:
        flash("Session is already removed.")
        return redirect(url_for("admin.dashboard"))
    now = datetime.now()
    target_session.deleted_at = now
    target_session.deleted_by_id = current_user.id
    for enrollment in target_session.enrollments:
        _notify_user(enrollment.student_id, "moderation", f"Your session for '{target_session.offer.title}' was removed by an administrator.", url_for("offers.offer_detail", offer_id=target_session.offer_id))
    db.session.commit()
    flash("Session removed. Its history has been preserved.")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/requests/<int:request_id>/delete", methods=["POST"])
def delete_request(request_id):
    learning_request = LearningRequest.query.get_or_404(request_id)
    if learning_request.deleted_at is not None:
        flash("Request is already removed.")
        return redirect(url_for("admin.dashboard"))
    learning_request.deleted_at = datetime.now()
    learning_request.deleted_by_id = current_user.id
    db.session.commit()
    flash("Request removed. Its record has been preserved.")
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


@admin_bp.route("/sessions/<int:session_id>/review")
def review_session_detail(session_id):
    target_session = Session.query.get_or_404(session_id)
    if target_session.deleted_at is not None:
        flash("This session has been removed and cannot be approved for a certificate.")
        return redirect(url_for("admin.dashboard"))
    confirmed = [e for e in target_session.enrollments if e.status == "confirmed"]
    attendance_complete = bool(confirmed) and all(e.attended is not None for e in confirmed)
    open_reports = Report.query.filter_by(session_id=target_session.id, status="open").order_by(Report.created_at.desc()).all()
    return render_template(
        "admin_session_review.html", session=target_session, confirmed_enrollments=confirmed,
        attendance_complete=attendance_complete, open_reports=open_reports,
        existing_certificate=Certificate.query.filter_by(session_id=target_session.id).first(),
    )


@admin_bp.route("/sessions/<int:session_id>/issue-certificate", methods=["POST"])
def issue_certificate(session_id):
    target_session = Session.query.get_or_404(session_id)
    offer = target_session.offer
    confirmed = [e for e in target_session.enrollments if e.status == "confirmed"]
    if target_session.deleted_at is not None or target_session.is_cancelled or not target_session.has_ended:
        flash("Only ended, active sessions can receive a certificate.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    if offer.approval_status != "approved":
        flash("The skill offer must be approved first.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    if not confirmed or any(e.attended is None for e in confirmed):
        flash("Attendance must be fully marked for at least one confirmed learner.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    if (
        not target_session.recording_url
        or target_session.recording_approval_status not in {"submitted", "approved"}
    ):
        flash(
            "The teacher must submit a recording before you can approve the session and issue its certificate."
        )
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    if Report.query.filter_by(session_id=target_session.id, status="open").count():
        flash("Resolve open reports about this session before issuing its certificate.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    existing = Certificate.query.filter_by(session_id=target_session.id).first()
    if existing:
        flash("A certificate has already been issued for this session.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))

    # Approve the recording and issue the certificate in one admin action.
    recording_was_not_approved = (
        target_session.recording_approval_status != "approved"
    )
    target_session.recording_approval_status = "approved"
    target_session.recording_review_note = None

    code = f"SS-{target_session.start_time.year}-{secrets.token_hex(4).upper()}"
    certificate = Certificate(
        certificate_code=code, session_id=target_session.id,
        recipient_id=offer.teacher_id, issued_by_id=current_user.id,
    )
    db.session.add(certificate)
    db.session.add(Notification(
        user_id=offer.teacher_id, category="certificate",
        message=f"Your SkillSync Certificate of Contribution for '{offer.title}' has been issued.",
        link=url_for("certificates.my_certificates"),
    ))
    if recording_was_not_approved:
        for enrollment in confirmed:
            db.session.add(Notification(
                user_id=enrollment.student_id,
                category="moderation",
                message=(
                    f"The recording for '{offer.title}' was approved "
                    "by the session reviewer."
                ),
                link=url_for("offers.offer_detail", offer_id=offer.id),
            ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A certificate already exists for this session. Refresh the review page.")
        return redirect(url_for("admin.review_session_detail", session_id=session_id))
    flash("Certificate issued. The teacher can download the PDF from My Certificates.")
    return redirect(url_for("admin.review_session_detail", session_id=session_id))
