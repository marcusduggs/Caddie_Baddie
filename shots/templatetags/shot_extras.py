from django import template
import os
import datetime

register = template.Library()

@register.filter
def file_mtime(path):
    """Return a naive UTC datetime for the file's mtime, or None if unavailable."""
    try:
        if not path:
            return None
        mtime = os.path.getmtime(path)
        return datetime.datetime.utcfromtimestamp(mtime)
    except Exception:
        return None
