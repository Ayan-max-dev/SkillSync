from flask import request
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()
login_manager = LoginManager()


def user_or_ip_key():
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return f"ip:{get_remote_address()}"


def login_key():
    # CHANGE "email" to your actual login form field name
    ident = (request.form.get("email") or "").strip().lower()
    return f"login:{ident}" if ident else f"ip:{get_remote_address()}"


limiter = Limiter(key_func=user_or_ip_key, default_limits=[])