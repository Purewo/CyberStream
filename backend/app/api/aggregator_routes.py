"""聚合搜索路由 —— 外部影视资源站搜索 / 详情 / magnet 解析。

把原 pc/aggregator/bridge.py（独立 10700 端口的本地桥）整合进后端 blueprint，
前端走统一的 API_BASE，不再需要手动起桥，web 端也能用。

约束（与抓取层反爬规则一致）：
- 每个请求只打一个 source，绝不在这里循环遍历所有源。rarbt 等有验证码 +
  频率限制，逐源由前端用户手动触发。
- btbtla 走本机代理（地址在 config.AGGREGATOR_BTBTLA_PROXY），其他源直连。

注意：抓取是同步阻塞 I/O，每个请求会占用一个 waitress 工作线程最多 ~12s
(sources/base.py 的 TIMEOUT)，rarbt 的 ddddocr 验证码路径可能更久。实验室
内测可接受；将来并发成问题再考虑线程池 / 把抓取移出请求线程。
"""

import logging

from flask import Blueprint, current_app, request

from backend.app.services.aggregator import (
    search_film, get_detail, get_magnet, SOURCE_NAMES, SOURCE_PRIORITY,
)
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

aggregator_bp = Blueprint('aggregator', __name__, url_prefix='/api/v1')


def _default_source() -> str:
    return current_app.config.get('AGGREGATOR_DEFAULT_SOURCE', 'rarbt')


def _proxy_for(source: str):
    """btbtla 需要本机代理，其他源直连。"""
    if source == 'btbtla':
        return current_app.config.get('AGGREGATOR_BTBTLA_PROXY')
    return None


@aggregator_bp.route('/aggregator/sources', methods=['GET'])
def aggregator_sources():
    return api_response(data={
        "sources": SOURCE_NAMES,
        "priority": SOURCE_PRIORITY,
        "default": _default_source(),
    })


@aggregator_bp.route('/aggregator/search', methods=['GET'])
def aggregator_search():
    keyword = (request.args.get('keyword') or '').strip()
    if not keyword:
        return api_error(40000, msg="keyword required")
    source = (request.args.get('source') or _default_source()).strip()
    try:
        page = int(request.args.get('page', '1') or '1')
    except ValueError:
        page = 1
    try:
        items = search_film(keyword, page=page, source=source, proxy=_proxy_for(source))
    except ValueError as exc:
        return api_error(40000, msg=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("aggregator search failed source=%s keyword=%s", source, keyword)
        return api_error(50000, msg=str(exc)[:300], http_status=500)
    return api_response(data={
        "source": source, "keyword": keyword, "page": page, "items": items or [],
    })


@aggregator_bp.route('/aggregator/detail', methods=['GET'])
def aggregator_detail():
    link = (request.args.get('link') or '').strip()
    if not link:
        return api_error(40000, msg="link required")
    source = (request.args.get('source') or _default_source()).strip()
    try:
        detail = get_detail(link, source=source, proxy=_proxy_for(source))
    except ValueError as exc:
        return api_error(40000, msg=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("aggregator detail failed source=%s link=%s", source, link)
        return api_error(50000, msg=str(exc)[:300], http_status=500)
    return api_response(data={"source": source, "link": link, "detail": detail})


@aggregator_bp.route('/aggregator/magnet', methods=['GET'])
def aggregator_magnet():
    link = (request.args.get('link') or '').strip()
    if not link:
        return api_error(40000, msg="link required")
    source = (request.args.get('source') or _default_source()).strip()
    try:
        magnet = get_magnet(link, source=source, proxy=_proxy_for(source))
    except ValueError as exc:
        return api_error(40000, msg=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("aggregator magnet failed source=%s link=%s", source, link)
        return api_error(50000, msg=str(exc)[:300], http_status=500)
    return api_response(data={"source": source, "link": link, "magnet": magnet})
