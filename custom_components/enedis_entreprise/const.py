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
CONF_MAILBOX = "mailbox"
CONF_SENDER = "sender"
CONF_DIRECTORY = "directory"
CONF_PRMS = "prms"

SOURCE_FOLDER = "folder"
SOURCE_IMAP = "imap"
SOURCE_FTPS = "ftps"

UPDATE_INTERVAL = timedelta(minutes=30)
# 5-minute points kept to rebuild an hour when its points arrive in several files or when a
# correction comes later (BEST data). Counted back from the newest point received.
POINT_RETENTION = timedelta(days=60)
STORAGE_VERSION = 1
