
from flask import jsonify
import time

def api_response(data=None, code=200, msg="success", http_status=200):
    """
    标准 API 成功响应
    """
    return jsonify({
        "code": code,
        "msg": msg,
        "trace_id": str(int(time.time())),
        "data": data
    }), http_status

def api_error(code=40000, msg="error", http_status=400):
    """
    标准 API 错误响应
    """
    return jsonify({
        "code": code,
        "msg": msg,
        "trace_id": str(int(time.time())),
        "data": None
    }), http_status
