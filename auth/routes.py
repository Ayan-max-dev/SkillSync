from urllib.parse import urlparse

from flask import abort, Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import limiter, login_key
from flask_limiter.util import get_remote_address
from models import User, db


auth_bp = Blueprint("auth", __name__)


def bounded_text(value, max_length):
    value = (value or "").strip()
    return value if len(value) <= max_length else None


def normalized_email(value):
    return (value or "").strip().lower()


@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@auth_bp.route("/add-user", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def add_user():
    abort(404)


def _safe_next_url(value):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return None
    return value


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", key_func=login_key, methods=["POST"])
@limiter.limit("600 per 5 minutes", key_func=get_remote_address, methods=["POST"])
def login():
    if current_user.is_authenticated:
        if current_user.must_change_password:
            return redirect(url_for("auth.change_password"))
        return redirect(url_for("main.dashboard"))

    next_url = _safe_next_url(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        email = normalized_email(bounded_text(request.form.get("email"), 120))
        password = request.form.get("password", "")
        if not email or not password or len(password) > 128:
            flash("Enter your email and password.", "warning")
            return redirect(url_for("auth.login", next=next_url))
        user = User.query.filter(db.func.lower(User.email) == email).first()

        if user and user.check_password(password):
            login_user(user)
            if user.must_change_password:
                return redirect(url_for("auth.change_password"))
            return redirect(next_url or url_for("main.dashboard"))
        flash("Invalid email or password.", "warning")
        return redirect(url_for("auth.login", next=next_url))

    return render_template("login.html")


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if not current_user.must_change_password:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")

        if not password or not 8 <= len(password) <= 128:
            flash("Your new password must be between 8 and 128 characters.", "warning")
            return redirect(url_for("auth.change_password"))
        if password != confirmation:
            flash("The password and confirmation must match.", "warning")
            return redirect(url_for("auth.change_password"))

        current_user.set_password(password)
        current_user.must_change_password = False
        db.session.commit()
        flash("Your password has been updated.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("change_password.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.home"))