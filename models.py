from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    grade = db.Column(db.String(20), nullable=True)
    courses_completed = db.Column(db.Text, nullable=True)  # free text, e.g. "AP Bio, Algebra II, Spanish 3"
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def profile_complete(self):
        return bool(self.grade and self.courses_completed)

    def _no_pending_attendance(self, session_ref):
        """Subquery: True if no enrollment on this session still has attended=None."""
        return ~db.session.query(Enrollment.id).filter(
            Enrollment.session_id == session_ref.id,
            Enrollment.attended.is_(None)
        ).exists()
    
    def _taught_sessions_query(self):
        """Sessions this user taught: ended, not cancelled, at least one
        confirmed enrollment, and attendance marked for every confirmed enrollment."""
        has_confirmed = (
            db.session.query(Enrollment.id)
            .filter(
                Enrollment.session_id == Session.id,
                Enrollment.status == "confirmed",
            )
            .exists()
        )
        no_pending_confirmed = ~(
            db.session.query(Enrollment.id)
            .filter(
                Enrollment.session_id == Session.id,
                Enrollment.status == "confirmed",
                Enrollment.attended.is_(None),
            )
            .exists()
        )
        return (
            db.session.query(Session)
            .join(Offer, Session.offer_id == Offer.id)
            .filter(
                Offer.teacher_id == self.id,
                Session.status != "cancelled",
                Session.deleted_at.is_(None),
                Session.recording_approval_status == "approved",
                Session.end_time < datetime.now(),
                has_confirmed,
                no_pending_confirmed,
            )
        )

    @property
    def sessions_taught_count(self):
        return self._taught_sessions_query().count()

    @property
    def skills_taught(self):
        """Distinct skills from offers that have at least one taught session."""
        seen = {}
        for session in self._taught_sessions_query().distinct():
            offer = session.offer
            if offer.skill.name not in seen:
                seen[offer.skill.name] = {"skill": offer.skill.name, "offer_title": offer.title}
        return list(seen.values())
    
    @property
    def average_teaching_rating(self):
        result = (
            db.session.query(func.avg(Feedback.rating))
            .join(Session, Feedback.session_id == Session.id)
            .join(Offer, Session.offer_id == Offer.id)
            .filter(Offer.teacher_id == self.id)
            .scalar()
        )
        return round(result, 1) if result is not None else None

    @property
    def total_ratings_count(self):
        return (
            db.session.query(Feedback)
            .join(Session, Feedback.session_id == Session.id)
            .join(Offer, Session.offer_id == Offer.id)
            .filter(Offer.teacher_id == self.id)
            .count()
        )

    @property
    def no_show_count(self):
        return Enrollment.query.filter_by(student_id=self.id, attended=False).count()

    @property
    def attended_count(self):
        return Enrollment.query.filter_by(student_id=self.id, attended=True).count()

    @property
    def skills_learned(self):
        confirmed_enrollments = (
            Enrollment.query
            .join(Session, Enrollment.session_id == Session.id)
            .filter(
                Enrollment.student_id == self.id,
                Enrollment.status == "confirmed",
                Enrollment.attended.is_(True),
                Session.recording_approval_status == "approved",
                Session.deleted_at.is_(None),
            )
            .all()
        )
        seen = {}
        for enrollment in confirmed_enrollments:
            offer = enrollment.session.offer
            skill_name = offer.skill.name
            if skill_name not in seen:
                seen[skill_name] = {"skill": skill_name, "offer_title": offer.title, "date": enrollment.session.start_time}
        return list(seen.values())

    @property
    def teaching_badges(self):
        count = self.sessions_taught_count
        badges = []
        if count >= 1:
            badges.append("First Class Taught")
        if count >= 5:
            badges.append("Regular Teacher")
        if count >= 10:
            badges.append("Master Teacher")
        return badges

    @property
    def learner_badges(self):
        return [f"Completed: {entry['skill']}" for entry in self.skills_learned]
    

class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # e.g. Technology, Music, Sports

class Offer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    level = db.Column(db.String(20), nullable=False)
    max_attendees = db.Column(db.Integer, default=10)
    status = db.Column(db.String(20), default="open")
    format = db.Column(db.String(20), default="live")  # "live" or "recorded"
    approval_status = db.Column(db.String(20), default="pending", nullable=False)  # pending / approved / rejected
    approval_note = db.Column(db.Text, nullable=True)
    material_url = db.Column(db.String(500), nullable=True)
    material_file = db.Column(db.String(255), nullable=True)
    material_name = db.Column(db.String(255), nullable=True)

    teacher = db.relationship("User", backref="offers")
    skill = db.relationship("Skill", backref="offers")

    @property
    def confirmed_count(self):
        return sum(1 for session in self.sessions for e in session.enrollments if e.status == "confirmed")

    @property
    def average_rating(self):
        all_feedback = [f for session in self.sessions for f in session.feedback]
        if not all_feedback:
            return None
        return round(sum(f.rating for f in all_feedback) / len(all_feedback), 1)


class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offer.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    video_url = db.Column(db.String(300), nullable=False)
    order = db.Column(db.Integer, default=0)  # controls playback/display order

    offer = db.relationship("Offer", backref="lessons")
        
class Request(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill.id"), nullable=False)
    description = db.Column(db.Text, nullable=True)
    preferred_time = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default="open")  # open / fulfilled / hidden
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    student = db.relationship(
    "User",
    foreign_keys=[student_id],
    backref="requests"
    )
    skill = db.relationship(
        "Skill",
        foreign_keys=[skill_id],
        backref="requests"
    )

class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offer.id"), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    meeting_link = db.Column(db.String(300), nullable=True)
    recording_url = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(20), default="scheduled")  # scheduled / cancelled
    cancelled_reason = db.Column(db.Text, nullable=True)

    offer = db.relationship("Offer", backref="sessions")

    RECORDING_GRACE_HOURS = 48
    recording_hidden = db.Column(db.Boolean, default=False, nullable=False)
    recording_approval_status = db.Column(db.String(20), default="none", nullable=False)  # none / submitted / approved / rejected
    recording_review_note = db.Column(db.Text, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    @property
    def has_ended(self):
        return self.end_time < datetime.now()

    @property
    def is_cancelled(self):
        return self.status == "cancelled"
    
    @property
    def is_completed(self):
        if self.is_cancelled or self.deleted_at is not None or not self.has_ended:
            return False

        confirmed = [
            e for e in self.enrollments
            if e.status == "confirmed"
        ]

        if not confirmed:
            return False

        return (
            self.recording_approval_status == "approved"
            and all(e.attended is not None for e in confirmed)
        )

    @property
    def is_missed(self):
        """True when the session ended and at least one confirmed
        student was marked absent."""
        if self.is_cancelled or not self.has_ended:
            return False

        return any(
            enrollment.status == "confirmed"
            and enrollment.attended is False
            for enrollment in self.enrollments
        )
    

    @property
    def recording_deadline(self):
        return self.end_time + timedelta(hours=self.RECORDING_GRACE_HOURS)

    @property
    def recording_status(self):
        if self.is_cancelled or self.deleted_at is not None:
            return "cancelled"
        if not self.has_ended:
            return "not_yet"
        if self.recording_hidden:
            return "removed"
        if self.recording_approval_status == "approved":
            return "uploaded"
        if self.recording_approval_status == "submitted":
            return "under_review"
        if self.recording_approval_status == "rejected":
            return "rejected"
        if self.recording_url:
            return "under_review"
        if datetime.now() <= self.recording_deadline:
            return "pending"
        return "overdue"

    # ... your existing thumbs/rating properties stay below
    @property
    def average_rating(self):
        if not self.feedback:
            return None
        return round(sum(f.rating for f in self.feedback) / len(self.feedback), 1)

    @property
    def rating_count(self):
        return len(self.feedback)


class Enrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="confirmed")  # confirmed / waitlisted
    attended = db.Column(db.Boolean, nullable=True)  # None = not marked yet, True/False once teacher marks it

    __table_args__ = (db.UniqueConstraint("session_id", "student_id", name="unique_session_enrollment"),)

    session = db.relationship("Session", backref="enrollments")
    student = db.relationship("User", backref="enrollments")
    

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1 = lowest rating, 5 = highest rating
    comment = db.Column(db.Text, nullable=True)

    __table_args__ = (db.UniqueConstraint("session_id", "student_id", name="unique_session_feedback"),)

    session = db.relationship("Session", backref="feedback")
    student = db.relationship("User", backref="feedback_given")

    
class RequestUpvote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    __table_args__ = (db.UniqueConstraint("request_id", "user_id", name="unique_request_upvote"),)

    request = db.relationship("Request", backref="upvotes")
    user = db.relationship("User", backref="request_upvotes")

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offer.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    hidden = db.Column(db.Boolean, default=False, nullable=False)
        
    offer = db.relationship("Offer", backref="comments")
    user = db.relationship("User", backref="comments")

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # enrollment / cancellation / feedback_reminder
    message = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(300), nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship("User", backref="notifications")

    @property
    def is_unread(self):
        return self.read_at is None
    
class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    offer_id = db.Column(db.Integer, db.ForeignKey("offer.id"), nullable=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"), nullable=True)  # recording report
    target_key = db.Column(db.String(50), nullable=False)  # e.g. "offer:12" — dedup key, sidesteps NULL-uniqueness gotcha
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="open")  # open / resolved / dismissed
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    reporter = db.relationship("User", foreign_keys=[reporter_id], backref="reports_filed")
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_id])
    offer = db.relationship("Offer", backref="reports")
    request = db.relationship("Request", backref="reports")
    comment = db.relationship("Comment", backref="reports")
    session = db.relationship("Session", backref="reports")

    __table_args__ = (
        db.UniqueConstraint("reporter_id", "target_key", name="unique_report_per_user_per_target"),
        db.CheckConstraint(
            "((offer_id IS NOT NULL) + (request_id IS NOT NULL) + (comment_id IS NOT NULL) + (session_id IS NOT NULL)) = 1",
            name="ck_report_exactly_one_target",
        ),
    )

    @property
    def target(self):
        return self.offer or self.request or self.comment or self.session

    @property
    def target_label(self):
        if self.offer:
            return f"Offer: {self.offer.title}"
        if self.request:
            return f"Request: {self.request.skill.name}"
        if self.comment:
            return f"Comment on {self.comment.offer.title}"
        if self.session:
            return f"Recording for {self.session.offer.title}"
        return "Unknown"