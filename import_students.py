"""Safely import student accounts from the SkillSync Excel workbooks."""

from __future__ import annotations

import argparse
import getpass
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from zipfile import ZipFile
from xml.etree import ElementTree

from flask import Flask

from models import User, db


EXCEL_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMAIL_LOCAL_PART = re.compile(r"^[^@\s]+$")
EMAIL_DOMAIN = "gemsed.com"


@dataclass(frozen=True)
class StudentRow:
    row_number: int
    name: str
    email: str
    grade: str


@dataclass
class ImportSummary:
    created: int = 0
    skipped_existing: int = 0
    duplicates: int = 0
    invalid: int = 0
    errors: list[str] = field(default_factory=list)


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _normalise_name(value: str) -> str:
    return _clean(value).title()


def _normalise_email(value: str) -> str:
    return _clean(value).lower()


def _read_sheet_rows(workbook: Path) -> Iterable[tuple[int, dict[str, str]]]:
    namespace = {"m": EXCEL_NAMESPACE, "r": RELATIONSHIP_NAMESPACE}
    with ZipFile(workbook) as archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise ValueError("The workbook is missing its Excel workbook metadata.")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", namespace):
                shared_strings.append(
                    "".join(text.text or "" for text in item.iter(f"{{{EXCEL_NAMESPACE}}}t"))
                )

        workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships_root = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        relationships = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships_root
        }
        sheets = workbook_root.find("m:sheets", namespace)
        if sheets is None or len(sheets) != 1:
            raise ValueError("The workbook must contain exactly one worksheet.")

        relationship_id = sheets[0].attrib[f"{{{RELATIONSHIP_NAMESPACE}}}id"]
        sheet_target = relationships.get(relationship_id)
        if not sheet_target:
            raise ValueError("The workbook worksheet relationship is invalid.")
        sheet_path = f"xl/{sheet_target}" if not sheet_target.startswith("xl/") else sheet_target
        sheet_root = ElementTree.fromstring(archive.read(sheet_path))

        rows = sheet_root.findall(".//m:sheetData/m:row", namespace)
        for row in rows:
            values: dict[str, str] = {}
            for cell in row.findall("m:c", namespace):
                value = cell.find("m:v", namespace)
                text = "" if value is None else value.text or ""
                if cell.attrib.get("t") == "s" and text:
                    text = shared_strings[int(text)]
                column = re.match(r"[A-Z]+", cell.attrib["r"])
                if column:
                    values[column.group(0)] = _clean(text)
            yield int(row.attrib["r"]), values


def _headers_and_columns(
    rows: list[tuple[int, dict[str, str]]],
) -> tuple[dict[str, str], list[tuple[int, dict[str, str]]]]:
    for index, (row_number, values) in enumerate(rows):
        headers = {value.lower(): column for column, value in values.items()}
        if "studentname" in headers and "username" in headers:
            return {
                "name": headers["studentname"],
                "class": headers["class"],
                "username": headers["username"],
            }, rows[index + 1 :]
        if "student name" in headers and "gems id" in headers:
            return {
                "name": headers["student name"],
                "class": headers["class"],
                "username": headers["gems id"],
            }, rows[index + 1 :]
    raise ValueError(
        "Unsupported workbook headers. Expected StudentName/Username or "
        "Student Name/Gems Id."
    )


def read_student_rows(workbook_path: str | Path) -> tuple[list[StudentRow], ImportSummary]:
    workbook = Path(workbook_path)
    if workbook.suffix.lower() != ".xlsx":
        raise ValueError("The input file must be an .xlsx workbook.")

    raw_rows = list(_read_sheet_rows(workbook))
    columns, data_rows = _headers_and_columns(raw_rows)
    summary = ImportSummary()
    students: list[StudentRow] = []
    seen: set[str] = set()

    for row_number, values in data_rows:
        name = _normalise_name(values.get(columns["name"]))
        username = _clean(values.get(columns["username"]))
        workbook_class = _clean(values.get(columns["class"]))
        email = _normalise_email(f"{username}@{EMAIL_DOMAIN}") if username else ""

        if (
            not name
            or not workbook_class
            or not username
            or not EMAIL_LOCAL_PART.fullmatch(username)
            or len(name) > 100
            or len(workbook_class) > 20
        ):
            summary.invalid += 1
            summary.errors.append(f"row {row_number}: missing or invalid name, username, or class")
            continue
        if email in seen:
            summary.duplicates += 1
            summary.errors.append(f"row {row_number}: duplicate email {email}")
            continue

        seen.add(email)
        grade = f"{workbook_class}th Grade" if workbook_class == "9" else workbook_class
        students.append(StudentRow(row_number, name, email, grade))

    return students, summary


def import_students(
    application: Flask,
    workbook_paths: Iterable[str | Path],
    password: str,
    *,
    dry_run: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    progress_every: int = 50,
) -> ImportSummary:
    if not password or not 8 <= len(password) <= 128:
        raise ValueError("The import password must be between 8 and 128 characters.")
    if progress_every < 1:
        raise ValueError("progress_every must be at least 1.")

    all_students: list[StudentRow] = []
    summary = ImportSummary()
    seen_across_workbooks: set[str] = set()
    with application.app_context():
        for workbook_path in workbook_paths:
            students, workbook_summary = read_student_rows(workbook_path)
            summary.invalid += workbook_summary.invalid
            summary.duplicates += workbook_summary.duplicates
            summary.errors.extend(
                f"{Path(workbook_path).name}: {error}"
                for error in workbook_summary.errors
            )
            for student in students:
                if student.email in seen_across_workbooks:
                    summary.duplicates += 1
                    summary.errors.append(
                        f"{Path(workbook_path).name} row {student.row_number}: "
                        f"duplicate email {student.email}"
                    )
                else:
                    seen_across_workbooks.add(student.email)
                    all_students.append(student)

        existing_emails = {
            email.lower()
            for (email,) in db.session.query(User.email).all()
        }
        new_students = [
            student for student in all_students if student.email not in existing_emails
        ]
        summary.skipped_existing = len(all_students) - len(new_students)

        if dry_run:
            summary.created = len(new_students)
            return summary

        try:
            total_new = len(new_students)
            for index, student in enumerate(new_students, start=1):
                user = User(
                    name=student.name,
                    email=student.email,
                    grade=student.grade,
                    is_admin=False,
                )
                user.set_password(password)
                db.session.add(user)
                if (
                    progress_callback
                    and (index % progress_every == 0 or index == total_new)
                ):
                    progress_callback(index, total_new)
            db.session.commit()
            summary.created = len(new_students)
        except BaseException:
            db.session.rollback()
            raise

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbooks", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--password-env",
        help="Read the temporary account password from this environment variable.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.password_env:
        import os

        password = os.environ.get(args.password_env, "")
        if not password:
            raise SystemExit(f"Environment variable {args.password_env} is empty or unset.")
    else:
        password = getpass.getpass("Temporary password for imported accounts: ")

    from app import app

    def report_progress(completed: int, total: int) -> None:
        print(f"processed {completed}/{total} new accounts")

    summary = import_students(
        app,
        args.workbooks,
        password,
        dry_run=args.dry_run,
        progress_callback=None if args.dry_run else report_progress,
    )
    print(
        f"created={summary.created} skipped_existing={summary.skipped_existing} "
        f"duplicates={summary.duplicates} invalid={summary.invalid}"
    )
    for error in summary.errors:
        print(f"warning: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
