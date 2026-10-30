import os
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from import_students import import_students
from models import User, db


def _write_workbook(path, headers, rows):
    shared = list(dict.fromkeys(headers + [value for row in rows for value in row]))
    shared_xml = "".join(
        f"<si><t>{value}</t></si>" for value in shared
    )
    shared_index = {value: index for index, value in enumerate(shared)}
    cells = []
    for row_number, row in enumerate([headers, *rows], start=1):
        cell_xml = []
        for column_number, value in enumerate(row):
            column = chr(ord("A") + column_number)
            cell_xml.append(
                f'<c r="{column}{row_number}" t="s"><v>{shared_index[value]}</v></c>'
            )
        cells.append(f'<row r="{row_number}">{"".join(cell_xml)}</row>')
    sheet = (
        f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(cells)}</sheetData></worksheet>"
    )
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared_xml}</sst>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)


@pytest.fixture
def temporary_app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def test_import_supports_both_workbook_formats_and_dry_run(tmp_path, temporary_app):
    grade9 = tmp_path / "grade9.xlsx"
    grade11 = tmp_path / "grade11.xlsx"
    _write_workbook(
        grade9,
        ["FeeID", "StudentNo", "StudentName", "Class", "Section", "Username"],
        [["1", "1", "AAHIL  AMANI", "9", "A", "AAHIL.A_OOW"]],
    )
    _write_workbook(
        grade11,
        ["S #", "Cmp ID", "Student Name", "Class", "Gems Id"],
        [["1", "2", "Arjun Biju", "11A", "arjun.b3_oow"]],
    )

    summary = import_students(
        temporary_app, [grade9, grade11], "password12345", dry_run=True
    )

    assert summary.created == 2
    assert User.query.count() == 0


def test_import_skips_existing_and_duplicate_emails_without_changes(tmp_path, temporary_app):
    workbook = tmp_path / "grade9.xlsx"
    _write_workbook(
        workbook,
        ["FeeID", "StudentNo", "StudentName", "Class", "Section", "Username"],
        [
            ["1", "1", "Existing Changed Name", "9", "A", "STUDENT_OOW"],
            ["2", "2", "Student Duplicate", "9", "A", "student_oow"],
            ["3", "3", "New Student", "9", "A", "NEW_OOW"],
        ],
    )
    existing = User(name="Original Name", email="student_oow@gemsed.com", grade="9th Grade")
    existing.set_password("old-password")
    db.session.add(existing)
    db.session.commit()

    summary = import_students(temporary_app, [workbook], "password12345")

    assert summary.created == 1
    assert summary.skipped_existing == 1
    assert summary.duplicates == 1
    assert User.query.filter_by(email="student_oow@gemsed.com").one().name == "Original Name"
    assert User.query.filter_by(email="new_oow@gemsed.com").one().check_password("password12345")


def test_import_rolls_back_on_unexpected_error(tmp_path, temporary_app, monkeypatch):
    workbook = tmp_path / "grade9.xlsx"
    _write_workbook(
        workbook,
        ["FeeID", "StudentNo", "StudentName", "Class", "Section", "Username"],
        [["1", "1", "New Student", "9", "A", "NEW_OOW"]],
    )
    original_commit = db.session.commit
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("failed")))

    with pytest.raises(RuntimeError):
        import_students(temporary_app, [workbook], "password12345")

    db.session.commit = original_commit
    assert User.query.count() == 0
