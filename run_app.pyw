"""
Glaze - Ceramic Glaze Formulator
Native desktop application launcher using pywebview
"""
import sys
import threading
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import webview
import uvicorn


def start_server():
    """Start the FastAPI server in a background thread."""
    from api.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def main():
    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to start
    time.sleep(1.5)

    # Create native window
    window = webview.create_window(
        title="Glaze - Ceramic Glaze Formulator",
        url="http://127.0.0.1:8000",
        width=1400,
        height=900,
        resizable=True,
        min_size=(1000, 700),
    )

    # Start webview (blocks until window is closed)
    webview.start()


if __name__ == "__main__":
    main()
