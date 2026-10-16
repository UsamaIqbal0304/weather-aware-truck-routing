"""WSGI entry points for a serverless host.

A serverless platform maps one file to one URL, and the function is handed
whatever path the platform's routing decided on — which is not always the
path the client asked for. Rather than depend on that, each entry point
below pins the path its Django URLconf should see. Routing is then decided
by this file and by ``config.urls``, not by a host-specific rewrite rule,
which is also what keeps ``manage.py runserver`` and the deployed app on
exactly the same code path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402  (must follow the path setup)


def entry_point(path: str) -> Callable:
    """A WSGI app that always presents ``path`` to Django."""

    def app(environ, start_response):
        environ["PATH_INFO"] = path
        environ["SCRIPT_NAME"] = ""
        return application(environ, start_response)

    return app
