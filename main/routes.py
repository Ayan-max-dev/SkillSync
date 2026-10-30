from datetime import datetime, timedelta
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy.orm import selectinload
from models import Certificate, Offer, Request, Enrollment, Skill, User, Session, db

main_bp = Blueprint("main", __name__)

ALLOWED_CATEGORIES = {
    "Technology & Computing",
    "Mathematics",
    "Science",
    "Languages",
    "Music",
    "Art & Design",
    "Communication & Public Speaking",
    "Writing & Literature",
    "Sports & Fitness",
    "Business & Entrepreneurship",
    "Academic Skills & Study Techniques",
    "Life Skills",
    "Other",
    "Academic",
    "Non-academic",
}
ALLOWED_FORMATS = {"live", "recorded"}
ALLOWED_LEVELS = {"Beginner", "Intermediate", "Advanced"}


def bounded_text(value, max_length):
    value = (value or "").strip()
    return value if len(value) <= max_length else None


def offer_relevance_score(offer, query):
    query = query.lower()
    title = offer.title.lower()
    description = (offer.description or "").lower()
    skill_name = offer.skill.name.lower()

    score = 0

    if query == skill_name or query in skill_name:
        score += 100
    if title.startswith(query):
        score += 70
    elif query in title:
        score += 40
    if query in description:
        score += 15

    return score


def request_relevance_score(req, query):
    query = query.lower()
    description = (req.description or "").lower()
    skill_name = req.skill.name.lower()

    score = 0

    if query == skill_name or query in skill_name:
        score += 100
    if query in description:
        score += 15

    return score


def _progress_sessions(user):
    taught_sessions = user._taught_sessions_query().order_by(Session.end_time.desc()).all()
    attended_sessions = (
        Session.query
        .join(Enrollment)
        .filter(
            Enrollment.student_id == user.id,
            Enrollment.status == "confirmed",
            Enrollment.attended.is_(True),
            Session.status != "cancelled",
            Session.recording_approval_status == "approved",
            Session.deleted_at.is_(None),
            Session.end_time < datetime.now(),
        )
        .distinct()
        .order_by(Session.end_time.desc())
        .all()
    )
    completed_sessions = {session.id: session for session in taught_sessions + attended_sessions}
    valid_durations = [
        (session.end_time - session.start_time).total_seconds() / 3600
        for session in completed_sessions.values()
        if session.start_time and session.end_time and session.end_time > session.start_time
    ]
    return taught_sessions, attended_sessions, completed_sessions, round(sum(valid_durations), 1)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    my_offers = (
        Offer.query
        .filter_by(teacher_id=current_user.id)
        .options(selectinload(Offer.sessions))
        .all()
    )
    my_requests = Request.query.filter_by(student_id=current_user.id).all()
    my_enrollments = (
        Enrollment.query
        .filter_by(student_id=current_user.id)
        .options(selectinload(Enrollment.session).selectinload(Session.offer))
        .all()
    )

    my_sessions = [s for offer in my_offers for s in offer.sessions]
    sessions_needing_recording = [s for s in my_sessions if s.recording_status in ("pending", "overdue")]

    soon_cutoff = datetime.now() + timedelta(hours=24)
    upcoming_teaching = [
        s for s in my_sessions
        if not s.is_cancelled and datetime.now() < s.start_time <= soon_cutoff
    ]
    upcoming_learning = [
        e.session for e in my_enrollments
        if e.status == "confirmed"
        and not e.session.is_cancelled
        and datetime.now() < e.session.start_time <= soon_cutoff
    ]
    certificates = (
        Certificate.query
        .filter_by(recipient_id=current_user.id)
        .order_by(Certificate.issued_at.desc())
        .limit(3)
        .all()
    )
    taught_sessions, attended_sessions, completed_sessions, _ = _progress_sessions(current_user)
    stats = {
        "skills_taught": len(current_user.skills_taught),
        "skills_learned": len(current_user.skills_learned),
        "sessions_taught": len(taught_sessions),
        "sessions_attended": len(attended_sessions),
        "sessions_completed": len(completed_sessions),
        "certificates": Certificate.query.filter_by(recipient_id=current_user.id).count(),
    }

    return render_template(
        "dashboard.html",
        my_offers=my_offers,
        my_requests=my_requests,
        my_enrollments=my_enrollments,
        sessions_needing_recording=sessions_needing_recording,
        upcoming_teaching=upcoming_teaching,
        upcoming_learning=upcoming_learning,
        stats=stats,
        certificates=certificates,
    )


@main_bp.route("/stats")
@login_required
def stats():
    taught_sessions, attended_sessions, completed_sessions, learning_hours = _progress_sessions(current_user)
    return render_template(
        "stats.html",
        taught_sessions=taught_sessions,
        attended_sessions=attended_sessions,
        completed_sessions=completed_sessions.values(),
        learning_hours=round(learning_hours, 1),
        certificate_count=Certificate.query.filter_by(recipient_id=current_user.id).count(),
    )


@main_bp.route("/explore")
def explore():
    category = request.args.get("category")
    format_filter = request.args.get("format")
    level_filter = request.args.get("level")
    search_query = bounded_text(request.args.get("q", ""), 100) or ""

    if category not in ALLOWED_CATEGORIES:
        category = None
    if format_filter not in ALLOWED_FORMATS:
        format_filter = None
    if level_filter not in ALLOWED_LEVELS:
        level_filter = None

    offers_query = (
        Offer.query
        .join(Skill)
        .filter(Offer.status == "open", Offer.approval_status == "approved")
        .options(
            selectinload(Offer.sessions).selectinload(Session.enrollments),
            selectinload(Offer.sessions).selectinload(Session.feedback),
            selectinload(Offer.skill),
        )
    )

    requests_query = (
        Request.query
        .join(Skill)
        .filter(Request.status == "open", Request.deleted_at.is_(None))
        .options(
            selectinload(Request.upvotes),
            selectinload(Request.skill)
        )
    )

    if category in ALLOWED_CATEGORIES:
        offers_query = offers_query.filter(db.or_(Offer.category == category, Offer.category.is_(None), Skill.category == category))
        requests_query = requests_query.filter(Skill.category == category)

    if format_filter in ("live", "recorded"):
        offers_query = offers_query.filter(Offer.format == format_filter)

    if level_filter in ("Beginner", "Intermediate", "Advanced"):
        offers_query = offers_query.filter(Offer.level == level_filter)

    if search_query:
        like_pattern = f"%{search_query}%"
        offers_query = offers_query.filter(
            db.or_(
                Offer.title.ilike(like_pattern),
                Offer.description.ilike(like_pattern),
                Skill.name.ilike(like_pattern),
            )
        )
        requests_query = requests_query.filter(
            db.or_(
                Request.description.ilike(like_pattern),
                Skill.name.ilike(like_pattern),
            )
        )

    offers_query = offers_query.order_by(Offer.id.desc())
    requests_query = requests_query.order_by(Request.id.desc())
    offers_page = offers_query.paginate(page=request.args.get("offers_page", 1, type=int), per_page=12, error_out=False)
    requests_page = requests_query.paginate(page=request.args.get("requests_page", 1, type=int), per_page=12, error_out=False)

    return render_template(
        "explore.html",
        offers=offers_page.items,
        requests=requests_page.items,
        offers_page=offers_page,
        requests_page=requests_page,
        selected_category=category,
        selected_format=format_filter,
        selected_level=level_filter,
        search_query=search_query,
    )


@main_bp.route("/users")
@login_required
def view_users():
    all_users = User.query.all()
    return render_template("users.html", users=all_users)