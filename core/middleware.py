"""Binds the acting user to the current thread so audit signals can record WHO.

Signals fire in the ORM layer, which has no access to the request. This middleware
is the only bridge between the two.
"""

import threading

_state = threading.local()


def get_actor():
    """Return (actor_id, actor_username, method, path) for the in-flight request."""
    return getattr(_state, "actor", (None, "", "", ""))


def set_actor(actor_id=None, username="", method="", path=""):
    _state.actor = (actor_id, username, method, path)


def clear_actor():
    _state.actor = (None, "", "", "")


class AuditActorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            set_actor(user.pk, user.get_username(), request.method, request.path[:255])
        else:
            set_actor(None, "", request.method, request.path[:255])
        try:
            return self.get_response(request)
        finally:
            clear_actor()
