"""
Django settings for the tattoo-ledger project.

Slice 0 — infrastructure only. There are no business models in this project yet.

Segregation of duties (BUILD_TASK §3.1, as corrected by KICKSTART §1): the two Django
apps `ops` and `acct` ARE the segregation. Django prefixes tables with the app label,
so the namespaces are `ops_*` and `acct_*` and grants are made by prefix. We do NOT
use two Postgres schemas — Django has no native multi-schema support and it would mean
hand-written db_table values or a database router.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = []
if rw := os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    ALLOWED_HOSTS.append(rw)
    CSRF_TRUSTED_ORIGINS.append(f"https://{rw}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # Platform infrastructure: dataset quarantine, audit log, database roles.
    "core",
    # The segregation. Both are deliberately EMPTY in Slice 0 — no models.
    "ops",
    "acct",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise sits directly after SecurityMiddleware (KICKSTART §3 Step 8).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Binds the acting user to the thread so the audit log can record WHO.
    "core.middleware.AuditActorMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Seed quarantine, DATA_REVIEW addendum §A1.3. The banner is a code
                # path, not a convention.
                "core.context_processors.dataset_banner",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SSL to the database: required in production, off locally.
#
# Overridable because Railway's PRIVATE network hostname
# (`postgres.railway.internal`) does not always terminate TLS, and
# `sslmode=require` against it fails with "server does not support SSL". That would
# fail the pre-deploy migrate — correctly, but for a reason that has nothing to do
# with the migration. Setting DJANGO_DB_SSL_REQUIRE=0 is then the right fix, and it
# is a variable change rather than a code change and redeploy.
#
# Turn it off ONLY for Railway's private hostname, which never leaves their network.
# If DATABASE_URL ever points at a public host, this must stay 1.
DB_SSL_REQUIRE = os.environ.get("DJANGO_DB_SSL_REQUIRE", "0" if DEBUG else "1") == "1"

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ["DATABASE_URL"], conn_max_age=600, ssl_require=DB_SSL_REQUIRE
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# The business, its bookkeeping and its close calendar are in Taiwan.
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}

# mail.E001: the console backend is flagged by `check --deploy`. This application
# sends no email. Notifications are Slice E and explicitly DEFERRED (BUILD_TASK §5),
# so there is nothing to configure an SMTP backend for yet. Revisit when Slice E
# is picked up — not before.
SILENCED_SYSTEM_CHECKS = ["mail.E001"]

# Behind Railway's proxy, trust the forwarded protocol so Django knows it is HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # Railway's healthcheck must not be answered with a 301.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    # One year, and only meaningful because Railway terminates TLS for every route.
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
