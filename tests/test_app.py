import io
import pytest
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import app, create_app
from models import (
    db,
    User,
    Skill,
    Offer,
    Session,
    Enrollment,
    Request,
    RequestUpvote,
    Feedback,
    Lesson,
    Comment,
    Notification,
)



@pytest.fixture
def client():
    test_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-secret-key",
    })

    with test_app.app_context():
        db.create_all()
        yield test_app.test_client()
        db.session.remove()
        db.drop_all()


def test_homepage(client):
    response = client.get("/")

    assert response.status_code == 200


def test_404_page(client):
    response = client.get("/this-page-does-not-exist")

    assert response.status_code == 404


def test_signup(client):
    response = client.post(
        "/add-user",
        data={
            "name": "Test Student",
            "email": "test@example.com",
            "password": "TestPassword123"
        },
        follow_redirects=True
    )

    assert response.status_code == 200

    user = User.query.filter_by(email="test@example.com").first()

    assert user is not None
    assert user.name == "Test Student"


def test_login(client):
    client.post(
        "/add-user",
        data={
            "name": "Test Student",
            "email": "test@example.com",
            "password": "TestPassword123"
        }
    )

    response = client.post(
        "/login",
        data={
            "email": "test@example.com",
            "password": "TestPassword123"
        },
        follow_redirects=True
    )

    assert response.status_code == 200


def test_join_session_requires_confirmed_enrollment_and_open_window(client):
    teacher = _create_user("Teacher", "teacher-join@example.com")
    student = _create_user("Student", "student-join@example.com")
    offer, _ = _create_offer(teacher, title="Join Test")
    offer.approval_status = "pending"
    session = Session(
        offer_id=offer.id,
        start_time=datetime.now() + timedelta(minutes=10),
        end_time=datetime.now() + timedelta(hours=1),
        meeting_link="https://example.com/meeting",
    )
    db.session.add(session)
    db.session.commit()

    _login(client, student.email)
    response = client.get(f"/sessions/{session.id}/join")
    assert response.status_code == 403

    enrollment = Enrollment(session_id=session.id, student_id=student.id, status="confirmed")
    db.session.add(enrollment)
    db.session.commit()
    response = client.get(f"/sessions/{session.id}/join")
    assert response.status_code == 302
    assert response.headers["Location"] == f"/offers/{offer.id}"


def test_material_upload_rejects_invalid_type_and_exact_five_mebibytes(client, tmp_path):
    teacher = _create_user("Material Teacher", "material-teacher@example.com")
    _login(client, teacher.email)
    client.application.config["MATERIAL_UPLOAD_FOLDER"] = str(tmp_path)

    fields = {
        "skill_name": "PDF Skills",
        "category": "Technology & Computing",
        "title": "PDF Skills",
        "description": "A useful description",
        "level": "Beginner",
        "format": "live",
        "max_attendees": "10",
    }
    invalid = client.post(
        "/offers/new",
        data={**fields, "material_file": (io.BytesIO(b"not a pdf"), "notes.exe")},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 302
    assert list(tmp_path.iterdir()) == []

    just_under_limit = b"%PDF-" + b"x" * (5 * 1024 * 1024 - 6)
    accepted = client.post(
        "/offers/new",
        data={**fields, "material_file": (io.BytesIO(just_under_limit), "valid.pdf")},
        content_type="multipart/form-data",
    )
    assert accepted.status_code == 302
    assert len(list(tmp_path.iterdir())) == 1

    exact_limit = b"%PDF-" + b"x" * (5 * 1024 * 1024 - 5)
    rejected = client.post(
        "/offers/new",
        data={**fields, "material_file": (io.BytesIO(exact_limit), "notes.pdf")},
        content_type="multipart/form-data",
    )
    assert rejected.status_code == 302
    assert len(list(tmp_path.iterdir())) == 1


def test_material_and_recording_visibility_are_authorized(client, tmp_path):
    teacher = _create_user("Visibility Teacher", "visibility-teacher@example.com")
    student = _create_user("Visibility Student", "visibility-student@example.com")
    stranger = _create_user("Visibility Stranger", "visibility-stranger@example.com")
    offer, _ = _create_offer(teacher, title="Visibility Test")
    offer.approval_status = "pending"
    offer.material_file = "existing.pdf"
    session = Session(
        offer_id=offer.id,
        start_time=datetime.now() - timedelta(hours=2),
        end_time=datetime.now() - timedelta(hours=1),
        recording_url="https://example.com/recording",
        recording_approval_status="approved",
    )
    db.session.add(session)
    db.session.commit()
    tmp_path.joinpath("existing.pdf").write_bytes(b"%PDF-1.7")
    client.application.config["MATERIAL_UPLOAD_FOLDER"] = str(tmp_path)

    _login(client, stranger.email)
    assert client.get(f"/offers/{offer.id}/material").status_code == 404
    assert client.get(f"/sessions/{session.id}/recording/view").status_code == 403

    offer.approval_status = "approved"
    db.session.commit()
    db.session.add(Enrollment(session_id=session.id, student_id=stranger.id, status="confirmed"))
    db.session.commit()
    material_response = client.get(f"/offers/{offer.id}/material")
    assert material_response.status_code == 200
    assert material_response.mimetype == "application/pdf"
    assert material_response.headers["Content-Disposition"].startswith("inline;")
    recording_response = client.get(f"/sessions/{session.id}/recording/view")
    assert recording_response.status_code == 302
    assert recording_response.headers["Location"] == session.recording_url


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")

    assert response.status_code == 302


def test_signup_rejects_invalid_email(client):
    response = client.post(
        "/add-user",
        data={
            "name": "Test Student",
            "email": "not-an-email",
            "password": "TestPassword123"
        }
    )

    assert response.status_code == 302

    user = User.query.filter_by(email="not-an-email").first()

    assert user is None

def test_duplicate_enrollment_rejected(client):
    user = User(
        name="Student",
        email="student@example.com"
    )
    user.set_password("TestPassword123")

    teacher = User(
        name="Teacher",
        email="teacher@example.com"
    )
    teacher.set_password("TestPassword123")

    skill = Skill(
        name="Python",
        category="Technology"
    )

    db.session.add_all([user, teacher, skill])
    db.session.commit()

    offer = Offer(
        teacher_id=teacher.id,
        skill_id=skill.id,
        title="Learn Python",
        level="Beginner"
    )

    db.session.add(offer)
    db.session.commit()

    session = Session(
        offer_id=offer.id,
        start_time=datetime.now(),
        end_time=datetime.now() + timedelta(hours=1)
    )

    db.session.add(session)
    db.session.commit()

    enrollment1 = Enrollment(
        session_id=session.id,
        student_id=user.id
    )

    db.session.add(enrollment1)
    db.session.commit()

    enrollment2 = Enrollment(
        session_id=session.id,
        student_id=user.id
    )

    db.session.add(enrollment2)

    with pytest.raises(Exception):
        db.session.commit()

    db.session.rollback()


def _create_user(name, email):
    user = User(name=name, email=email)
    user.set_password("TestPassword123")
    db.session.add(user)
    db.session.flush()
    return user


def _create_offer(teacher, title="Test Offer"):
    skill = Skill(name=f"Skill {title}", category="Academic")
    db.session.add(skill)
    db.session.flush()
    offer = Offer(
        teacher_id=teacher.id,
        skill_id=skill.id,
        title=title,
        level="Beginner",
    )
    db.session.add(offer)
    db.session.commit()
    return offer, skill


def _login(client, email):
    user = User.query.filter_by(email=email).one()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_offer_owner_can_delete_offer_without_sessions(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    offer, _ = _create_offer(teacher)
    offer_id = offer.id
    _login(client, teacher.email)

    response = client.post(f"/offers/{offer_id}/delete")

    assert response.status_code == 302
    assert db.session.get(Offer, offer_id) is None


def test_other_user_cannot_delete_offer(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    other = _create_user("Other", "other@example.com")
    offer, _ = _create_offer(teacher)
    _login(client, other.email)

    response = client.post(f"/offers/{offer.id}/delete")

    assert response.status_code == 403
    assert db.session.get(Offer, offer.id) is not None


def test_offer_with_session_cannot_be_deleted(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    offer, _ = _create_offer(teacher)
    session = Session(
        offer_id=offer.id,
        start_time=datetime.now(),
        end_time=datetime.now() + timedelta(hours=1),
    )
    db.session.add(session)
    db.session.commit()
    _login(client, teacher.email)

    response = client.post(f"/offers/{offer.id}/delete")

    assert response.status_code == 302
    assert db.session.get(Offer, offer.id) is not None
    assert db.session.get(Session, session.id) is not None


def test_deleting_offer_removes_lessons_comments_but_not_teacher(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    offer, _ = _create_offer(teacher)
    lesson = Lesson(
        offer_id=offer.id,
        title="Part One",
        video_url="https://example.com/video",
    )
    comment = Comment(
        offer_id=offer.id,
        user_id=teacher.id,
        content="Useful note",
    )
    db.session.add_all([lesson, comment])
    db.session.commit()
    lesson_id, comment_id, teacher_id = lesson.id, comment.id, teacher.id
    offer_id = offer.id
    _login(client, teacher.email)

    response = client.post(f"/offers/{offer_id}/delete")

    assert response.status_code == 302
    assert db.session.get(Offer, offer_id) is None
    assert db.session.get(Lesson, lesson_id) is None
    assert db.session.get(Comment, comment_id) is None
    assert db.session.get(User, teacher_id) is not None


def test_request_owner_can_delete_request_and_upvotes_but_not_skill(client):
    owner = _create_user("Owner", "owner@example.com")
    voter = _create_user("Voter", "voter@example.com")
    skill = Skill(name="Shared Skill", category="Academic")
    db.session.add(skill)
    db.session.flush()
    learning_request = Request(
        student_id=owner.id,
        skill_id=skill.id,
        description="Learn this",
    )
    db.session.add(learning_request)
    db.session.flush()
    upvote = RequestUpvote(request_id=learning_request.id, user_id=voter.id)
    db.session.add(upvote)
    db.session.commit()
    request_id, upvote_id, skill_id = learning_request.id, upvote.id, skill.id
    _login(client, owner.email)

    response = client.post(f"/requests/{request_id}/delete")

    assert response.status_code == 302
    assert db.session.get(Request, request_id) is None
    assert db.session.get(RequestUpvote, upvote_id) is None
    assert db.session.get(Skill, skill_id) is not None


def test_other_user_cannot_delete_request(client):
    owner = _create_user("Owner", "owner@example.com")
    other = _create_user("Other", "other@example.com")
    skill = Skill(name="Request Skill", category="Academic")
    db.session.add(skill)
    db.session.flush()
    request_record = Request(
        student_id=owner.id,
        skill_id=skill.id,
        description="Learn this",
    )
    db.session.add(request_record)
    db.session.commit()
    _login(client, other.email)

    response = client.post(f"/requests/{request_record.id}/delete")

    assert response.status_code == 403
    assert db.session.get(Request, request_record.id) is not None


def test_comment_author_can_delete_comment_only(client):
    author = _create_user("Author", "author@example.com")
    offer, _ = _create_offer(author)
    comment = Comment(offer_id=offer.id, user_id=author.id, content="Delete me")
    db.session.add(comment)
    db.session.commit()
    comment_id, offer_id, author_id = comment.id, offer.id, author.id
    _login(client, author.email)

    response = client.post(f"/comments/{comment_id}/delete")

    assert response.status_code == 302
    assert db.session.get(Comment, comment_id) is None
    assert db.session.get(Offer, offer_id) is not None
    assert db.session.get(User, author_id) is not None


def test_other_user_cannot_delete_comment(client):
    author = _create_user("Author", "author@example.com")
    other = _create_user("Other", "other@example.com")
    offer, _ = _create_offer(author)
    comment = Comment(offer_id=offer.id, user_id=author.id, content="Keep me")
    db.session.add(comment)
    db.session.commit()
    _login(client, other.email)

    response = client.post(f"/comments/{comment.id}/delete")

    assert response.status_code == 403
    assert db.session.get(Comment, comment.id) is not None


def test_offer_teacher_can_delete_lesson_only(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    offer, _ = _create_offer(teacher)
    lesson = Lesson(
        offer_id=offer.id,
        title="Part One",
        video_url="https://example.com/video",
    )
    db.session.add(lesson)
    db.session.commit()
    lesson_id, offer_id = lesson.id, offer.id
    _login(client, teacher.email)

    response = client.post(f"/lessons/{lesson_id}/delete")

    assert response.status_code == 302
    assert db.session.get(Lesson, lesson_id) is None
    assert db.session.get(Offer, offer_id) is not None


def test_other_user_cannot_delete_lesson(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    other = _create_user("Other", "other@example.com")
    offer, _ = _create_offer(teacher)
    lesson = Lesson(
        offer_id=offer.id,
        title="Part One",
        video_url="https://example.com/video",
    )
    db.session.add(lesson)
    db.session.commit()
    _login(client, other.email)

    response = client.post(f"/lessons/{lesson.id}/delete")

    assert response.status_code == 403
    assert db.session.get(Lesson, lesson.id) is not None


@pytest.mark.parametrize("path", [
    "/offers/1/delete",
    "/requests/1/delete",
    "/comments/1/delete",
    "/lessons/1/delete",
])
def test_get_delete_routes_do_not_delete(client, path):
    response = client.get(path)

    assert response.status_code == 405


@pytest.mark.parametrize("path", [
    "/offers/1/delete",
    "/requests/1/delete",
    "/comments/1/delete",
    "/lessons/1/delete",
])
def test_unauthenticated_delete_routes_require_login(client, path):
    response = client.post(path)

    assert response.status_code == 302


def test_delete_routes_require_csrf_when_enabled(client):
    teacher = _create_user("Teacher", "teacher@example.com")
    offer, _ = _create_offer(teacher)
    client.application.config["WTF_CSRF_ENABLED"] = True
    with client.session_transaction() as session:
        session["_user_id"] = str(teacher.id)
        session["_fresh"] = True

    response = client.post(f"/offers/{offer.id}/delete")

    assert response.status_code == 400
    assert db.session.get(Offer, offer.id) is not None

def test_duplicate_upvote_rejected(client):
    user = User(
        name="Student",
        email="student@example.com"
    )
    user.set_password("TestPassword123")

    skill = Skill(
        name="Python",
        category="Technology"
    )

    db.session.add_all([user, skill])
    db.session.commit()

    request = Request(
        student_id=user.id,
        skill_id=skill.id,
        description="I want to learn Python"
    )

    db.session.add(request)
    db.session.commit()

    upvote1 = RequestUpvote(
        request_id=request.id,
        user_id=user.id
    )

    db.session.add(upvote1)
    db.session.commit()

    upvote2 = RequestUpvote(
        request_id=request.id,
        user_id=user.id
    )

    db.session.add(upvote2)

    with pytest.raises(Exception):
        db.session.commit()

    db.session.rollback()


def test_new_offer_starts_pending_and_is_not_in_explore(client):
    teacher = _create_user("Teacher", "teacher2@example.com")
    teacher.grade = "10"
    teacher.courses_completed = "Math"
    db.session.commit()
    _login(client, teacher.email)
    response = client.post("/offers/new", data={
        "skill_name": "Python", "category": "Academic", "title": "Python Basics",
        "description": "I will teach Python basics", "level": "Beginner",
        "format": "live", "max_attendees": "10"
    }, follow_redirects=False)
    assert response.status_code == 302
    offer = Offer.query.filter_by(title="Python Basics").one()
    assert offer.approval_status == "pending"
    explore = client.get("/explore")
    assert b"Python Basics" not in explore.data


def test_new_offer_notifies_admin_for_review(client):
    teacher = _create_user("Teacher", "offer-notify-teacher@example.com")
    admin = _create_user("Admin", "offer-notify-admin@example.com")
    admin.is_admin = True
    teacher.grade = "10"
    teacher.courses_completed = "Math"
    db.session.commit()
    _login(client, teacher.email)

    response = client.post("/offers/new", data={
        "skill_name": "Algebra", "category": "Mathematics", "title": "Algebra Basics",
        "description": "I will teach algebra basics", "level": "Beginner",
        "format": "live", "max_attendees": "10"
    })

    assert response.status_code == 302
    notification = Notification.query.filter_by(
        user_id=admin.id,
        category="moderation",
    ).one()
    assert "Algebra Basics" in notification.message
    assert notification.link == "/admin/dashboard?offers_page=1"


def test_login_email_is_case_insensitive(client):
    user = _create_user("Case User", "case-user@example.com")
    user.set_password("TestPassword123")
    db.session.commit()

    response = client.post("/login", data={
        "email": "CASE-USER@EXAMPLE.COM",
        "password": "TestPassword123",
    })

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_registration_normalizes_name(client):
    response = client.post("/add-user", data={
        "name": "  aAHIL   aMANI ",
        "email": "normalized@example.com",
        "password": "TestPassword123",
    })

    assert response.status_code == 302
    assert db.session.query(User).filter_by(email="normalized@example.com").one().name == "Aahil Amani"


def test_admin_can_approve_offer(client):
    teacher = _create_user("Teacher", "teacher3@example.com")
    admin = _create_user("Admin", "admin3@example.com")
    admin.is_admin = True
    skill = Skill(name="Chess", category="Non-academic")
    db.session.add(skill); db.session.commit()
    offer = Offer(teacher_id=teacher.id, skill_id=skill.id, title="Chess", description="Chess basics", level="Beginner", approval_status="pending")
    db.session.add(offer); db.session.commit()
    _login(client, admin.email)
    response = client.post(f"/admin/offers/{offer.id}/review", data={"action":"approve"})
    assert response.status_code == 302
    assert db.session.get(Offer, offer.id).approval_status == "approved"


def test_admin_review_page_does_not_remove_recording_from_queue(client):
    admin = _create_user("Admin", "recording-queue-admin@example.com")
    admin.is_admin = True
    teacher = _create_user("Recording Teacher", "recording-queue-teacher@example.com")
    offer, _ = _create_offer(teacher, "Queue Recording")
    session = Session(
        offer_id=offer.id,
        start_time=datetime.now() - timedelta(hours=2),
        end_time=datetime.now() - timedelta(hours=1),
        recording_url="https://example.com/recording",
        recording_approval_status="submitted",
    )
    db.session.add(session)
    db.session.commit()
    _login(client, admin.email)

    response = client.get(f"/admin/sessions/{session.id}/review")

    assert response.status_code == 200
    assert db.session.get(Session, session.id).recording_approval_status == "submitted"
    dashboard = client.get("/admin/dashboard")
    assert b"Queue Recording" in dashboard.data


def test_admin_can_reject_session_completion(client):
    admin = _create_user("Admin", "completion-admin@example.com")
    admin.is_admin = True
    teacher = _create_user("Completion Teacher", "completion-teacher@example.com")
    offer, _ = _create_offer(teacher, "Completion Review")
    session = Session(
        offer_id=offer.id,
        start_time=datetime.now() - timedelta(hours=2),
        end_time=datetime.now() - timedelta(hours=1),
        recording_url="https://example.com/recording",
        recording_approval_status="submitted",
    )
    db.session.add(session)
    db.session.commit()
    _login(client, admin.email)

    response = client.post(
        f"/admin/sessions/{session.id}/reject-completion",
        data={"review_note": "Please provide a clearer recording."},
    )

    assert response.status_code == 302
    saved = db.session.get(Session, session.id)
    assert saved.recording_approval_status == "rejected"
    assert saved.recording_review_note == "Please provide a clearer recording."


def test_recording_requires_admin_approval_for_completion(client):
    teacher = _create_user("Teacher", "teacher4@example.com")
    student = _create_user("Student", "student4@example.com")
    skill = Skill(name="Python", category="Academic")
    db.session.add(skill); db.session.commit()
    offer = Offer(teacher_id=teacher.id, skill_id=skill.id, title="Python", description="Learn Python", level="Beginner", approval_status="approved")
    db.session.add(offer); db.session.commit()
    session = Session(offer_id=offer.id, start_time=datetime.now()-timedelta(hours=2), end_time=datetime.now()-timedelta(hours=1), recording_url="https://example.com/recording", recording_approval_status="submitted")
    db.session.add(session); db.session.commit()
    enrollment = Enrollment(session_id=session.id, student_id=student.id, status="confirmed", attended=True)
    db.session.add(enrollment); db.session.commit()
    assert session.is_completed is False
    admin = _create_user("Admin", "admin4@example.com"); admin.is_admin = True; db.session.commit()
    _login(client, admin.email)
    response = client.post(f"/admin/sessions/{session.id}/recording-review", data={"action":"approve"})
    assert response.status_code == 302
    assert db.session.get(Session, session.id).recording_approval_status == "approved"
    assert db.session.get(Session, session.id).is_completed is True


def test_admin_soft_deletes_session(client):
    teacher = _create_user("Teacher", "teacher5@example.com")
    admin = _create_user("Admin", "admin5@example.com"); admin.is_admin = True
    skill = Skill(name="Chess", category="Non-academic")
    db.session.add(skill); db.session.commit()
    offer = Offer(teacher_id=teacher.id, skill_id=skill.id, title="Chess", description="Chess", level="Beginner", approval_status="approved")
    db.session.add(offer); db.session.commit()
    session = Session(offer_id=offer.id, start_time=datetime.now()+timedelta(hours=1), end_time=datetime.now()+timedelta(hours=2))
    db.session.add(session); db.session.commit()
    _login(client, admin.email)
    response = client.post(f"/admin/sessions/{session.id}/delete")
    assert response.status_code == 302
    saved = db.session.get(Session, session.id)
    assert saved is not None and saved.deleted_at is not None
