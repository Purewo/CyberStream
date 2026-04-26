import logging
import threading

from flask import Blueprint, current_app

from backend.app.services.scanner import scanner_engine
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__, url_prefix='/api/v1')


def _scan_background_task(app):
    with app.app_context():
        try:
            scanner_engine.scan(lock_acquired=True)
        except Exception as e:
            logger.exception("Background scan failed error=%s", e)


@system_bp.route('/scan', methods=['GET'])
def get_scan_status():
    return api_response(data=scanner_engine.get_status())


@system_bp.route('/scan', methods=['POST'])
def trigger_scan():
    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg="Scanner is already running", http_status=429)

    app = current_app._get_current_object()
    thread = threading.Thread(target=_scan_background_task, args=(app,))
    thread.start()
    return api_response(msg="Scan task accepted", http_status=202)
