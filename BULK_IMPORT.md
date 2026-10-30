# Bulk student-account import

`import_students.py` imports the existing Grade 9 and Grade 11 `.xlsx` formats without
dropping tables or modifying existing users. Ordinary users are students in the current
model (`is_admin=False`); there is no separate role column.

The importer:

- Detects the workbook headers (`StudentName`/`Username` or `Student Name`/`Gems Id`).
- Normalizes names and email addresses, and uses the `gemsed.com` domain.
- Detects duplicate emails case-insensitively within and across workbooks.
- Skips existing email addresses without changing those users.
- Validates all rows before writing.
- Uses `User.set_password()` and never prints passwords or hashes.
- Supports a dry run and rolls back on unexpected database errors.
- Prints count-only progress every 50 newly created accounts during a real import;
  dry-run output remains a summary and never writes to the database.

Password hashing remains the import's dominant cost. The importer keeps the
application's Werkzeug password-hashing settings and does not weaken or parallelize
hashing. Database lookup overhead is reduced to one email-column query, followed by
case normalization in memory.

## Local commands

From the project directory, set `SECRET_KEY` as usual, then preview both workbooks:

```powershell
$env:SECRET_KEY = "your-existing-secret"
$env:IMPORT_PASSWORD = "your-temporary-password"
py import_students.py --dry-run --password-env IMPORT_PASSWORD `
  ".\SkillSync App Gr9 List.xlsx" `
  ".\Grade 11 - class list_SkillSync.xlsx"
```

After reviewing the summary, run the same command without `--dry-run`:

```powershell
py import_students.py --password-env IMPORT_PASSWORD `
  ".\SkillSync App Gr9 List.xlsx" `
  ".\Grade 11 - class list_SkillSync.xlsx"
```

The script resolves the database from the application configuration. It does not call
`drop_all()` and does not replace the SQLite file.

## PythonAnywhere commands

1. Back up the live `instance/skillshare.db` file using the PythonAnywhere console.
2. Upload the workbooks and `import_students.py` to the deployed project directory.
3. From that directory, activate the same virtual environment used by the web app.
4. Confirm the application configuration points to the intended live database.
5. Run a dry run first, providing the password through an environment variable or the
   hidden prompt:

```bash
export IMPORT_PASSWORD='your-temporary-password'
python import_students.py --dry-run --password-env IMPORT_PASSWORD \
  'SkillSync App Gr9 List.xlsx' \
  'Grade 11 - class list_SkillSync.xlsx'
```

6. Review the counts, then run the command again without `--dry-run`.
7. Reload the PythonAnywhere web app and test one account.
8. Remove the workbook and unset the temporary environment variable when finished.

Do not run `seed.py` for this task: it drops and recreates the database.
