from dotenv import load_dotenv
import os

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
        basedir, "instance", "skillshare.db"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}
    APPLICATION_TIMEZONE = os.environ.get("APPLICATION_TIMEZONE", "UTC")
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024
    MATERIAL_MAX_BYTES = 5 * 1024 * 1024
    MATERIAL_UPLOAD_FOLDER = os.environ.get(
        "MATERIAL_UPLOAD_FOLDER",
        os.path.join(basedir, "instance", "materials"),
    )

    SESSION_COOKIE_SECURE = os.environ.get("PRODUCTION") == "1"
    SESSION_COOKIE_HTTPONLY = True