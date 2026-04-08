"""Remote control application package."""


def main():
    from .server_app import main as server_main

    return server_main()


__all__ = ["main"]
