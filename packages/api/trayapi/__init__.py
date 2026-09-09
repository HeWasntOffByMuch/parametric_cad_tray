from .version import API_VERSION

__all__ = ["API_VERSION", "create_app"]


def create_app(*args, **kwargs):
    from .main import create_app as _create_app

    return _create_app(*args, **kwargs)
