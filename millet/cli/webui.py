"""millet webui command."""
from __future__ import annotations

import click


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind")
@click.option("--port", default=8765, show_default=True, type=int, help="Port to bind")
@click.option("--open-browser", is_flag=True, default=False, help="Open the browser after startup")
def webui(host: str, port: int, open_browser: bool) -> None:
    """Launch the local browser control panel."""
    from millet.webui import run_server

    run_server(host=host, port=port, open_browser=open_browser)
