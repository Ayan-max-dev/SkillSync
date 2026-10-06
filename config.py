from dotenv import load_dotenv
import os

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = "sqlite:///skillshare.db"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    MATERIAL_UPLOAD_FOLDER = os.path.join(basedir, "instance", "materials")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable is not set")
