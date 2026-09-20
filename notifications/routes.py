from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_login import current_user, login_required

from models import Notification, db

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/notifications")
@login_required
def view_notifications():
    notifications = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template("notifications.html", notifications=notifications)


@notifications_bp.route("/notifications/<int:notification_id>/open", methods=["POST"])
@login_required
def open_notification(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != current_user.id:
        abort(403)

    if notification.is_unread:
        notification.read_at = datetime.now()
        db.session.commit()

    return redirect(notification.link or url_for("notifications.view_notifications"))


@notifications_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, read_at=None).update({"read_at": datetime.now()})
    db.session.commit()
    return redirect(url_for("notifications.view_notifications"))