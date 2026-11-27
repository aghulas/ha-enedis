"""Constants of the Enedis entreprise integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "enedis_entreprise"

CONF_SOURCE = "source"
CONF_KEY = "key"
CONF_PATH = "path"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DIRECTORY = "directory"
CONF_PRMS = "prms"
CONF_HOST_KEY = "host_key"
CONF_PRM = "prm"
CONF_OVERWRITE = "overwrite"
CONF_ENTRY_ID = "config_entry_id"
SERVICE_IMPORT_HISTORY = "import_history"
CONF_NO_FILE_DAYS = "no_file_days"
DEFAULT_NO_FILE_DAYS = 3

SOURCE_FOLDER = "folder"
# Mailbox source of the development versions, removed in 0.1.0: an entry that still has it is
# refused at setup with a repair issue (see __init__.py).
SOURCE_IMAP = "imap"
# Fields of that source, still redacted from the diagnostics of such an entry.
LEGACY_SECRET_FIELDS = ("mailbox", "sender")
SOURCE_FTPS = "ftps"
SOURCE_SFTP = "sftp"

UPDATE_INTERVAL = timedelta(minutes=30)
# 5-minute points kept to rebuild an hour when its points arrive in several files or when a
# correction comes later (BEST data). Counted back from the newest point received.
POINT_RETENTION = timedelta(days=60)
STORAGE_VERSION = 1
