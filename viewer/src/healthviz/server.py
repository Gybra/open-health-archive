"""Run Streamlit's public CLI without Python-side outbound connections."""

import ipaddress
import runpy
import sys


def deny_network(event: str, args: tuple) -> None:
    if event in ("socket.connect", "socket.gethostbyname", "socket.gethostbyaddr"):
        raise PermissionError("viewer: outbound connections are disabled")
    if event == "socket.getaddrinfo" and args[0] is not None:
        try:
            ipaddress.ip_address(args[0])
        except ValueError:
            raise PermissionError("viewer: outbound DNS is disabled") from None


if __name__ == "__main__":
    # Install before framework startup; basemap requests belong to the browser only.
    sys.addaudithook(deny_network)
    runpy.run_module("streamlit", run_name="__main__", alter_sys=True)
