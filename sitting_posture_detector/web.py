"""Flask web: MJPEG /video_feed, /api/status, trang chủ."""
import logging
import threading

from flask import Flask, Response, jsonify, render_template_string
from werkzeug.serving import make_server

import config
from display import INDEX_HTML
from state import GlobalState

log = logging.getLogger(__name__)


def create_app(state: GlobalState) -> Flask:
    app = Flask(__name__)

    def mjpeg():
        seq = 0
        while not state.stop_event.is_set():
            item = state.wait_jpeg(seq, timeout=1.0)
            if item is None:
                continue
            jpeg, seq = item
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")

    @app.get("/")
    def index():
        return render_template_string(INDEX_HTML)

    @app.get("/video_feed")
    def video_feed():
        resp = Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    @app.get("/api/status")
    def api_status():
        resp = jsonify(state.get_status())
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


class WebServer:
    """Chạy Flask trong một thread riêng, có thể dừng sạch."""

    def __init__(self, state: GlobalState, host: str = config.WEB_HOST, port: int = config.WEB_PORT):
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        self._server = make_server(host, port, create_app(state), threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, name="web", daemon=True)
        self.host, self.port = host, port

    def start(self) -> None:
        self._thread.start()
        log.info("Web stream: http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._thread.is_alive():
            self._server.shutdown()
            self._thread.join(timeout=3)
