"""聚合搜索路由 —— 外部影视资源站搜索 / 详情 / magnet 解析。

把原 pc/aggregator/bridge.py（独立 10700 端口的本地桥）整合进后端 blueprint，
前端走统一的 API_BASE，不再需要手动起桥，web 端也能用。

约束（与抓取层反爬规则一致）：
- 每个请求只打一个 source，绝不在这里循环遍历所有源。rarbt 等有验证码 +
  频率限制，逐源由前端用户手动触发。
- btbtla/rarbt 可走本机代理（优先单源配置，回退统一聚合代理），其他源直连。

注意：抓取是同步阻塞 I/O，每个请求会占用一个 Web 工作线程最多 ~12s
(sources/base.py 的 TIMEOUT)，rarbt 的 ddddocr 验证码路径可能更久。实验室
内测可接受；将来并发成问题再考虑线程池 / 把抓取移出请求线程。
"""

import logging

from flask import Blueprint, current_app, request

from backend.app.services.aggregator import (
    search_film, get_detail, get_magnet, SourceBusyError,
    SOURCE_NAMES, SOURCE_PRIORITY,
)
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

aggregator_bp = Blueprint('aggregator', __name__, url_prefix='/api/v1')

MAX_KEYWORD_LENGTH = 120
MAX_LINK_LENGTH = 2048
MAX_PAGE = 50


def _default_source() -> str:
    return current_app.config.get('AGGREGATOR_DEFAULT_SOURCE', 'rarbt')


def _request_source():
    source = (request.args.get('source') or _default_source()).strip().lower()
    if source not in SOURCE_NAMES:
        return None, api_error(40000, msg=f"unknown source: {source}", http_status=400)
    return source, None


def _request_page():
    raw = (request.args.get('page', '1') or '1').strip()
    try:
        page = int(raw)
    except ValueError:
        return None, api_error(40000, msg="page must be an integer", http_status=400)
    if page < 1 or page > MAX_PAGE:
        return None, api_error(40000, msg=f"page must be between 1 and {MAX_PAGE}", http_status=400)
    return page, None


def _proxy_for(source: str):
    """返回需要代理的聚合源代理地址。"""
    if source == 'btbtla':
        return (
            current_app.config.get('AGGREGATOR_BTBTLA_PROXY')
            or current_app.config.get('AGGREGATOR_PROXY_URL')
            or None
        )
    if source == 'rarbt':
        return (
            current_app.config.get('AGGREGATOR_RARBT_PROXY')
            or current_app.config.get('AGGREGATOR_PROXY_URL')
            or None
        )
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
    if len(keyword) > MAX_KEYWORD_LENGTH:
        return api_error(40000, msg=f"keyword must be at most {MAX_KEYWORD_LENGTH} characters")
    source, error = _request_source()
    if error:
        return error
    page, error = _request_page()
    if error:
        return error
    try:
        items = search_film(keyword, page=page, source=source, proxy=_proxy_for(source))
    except SourceBusyError:
        return api_error(42900, msg="aggregator source is busy", http_status=429)
    except ValueError as exc:
        return api_error(40000, msg=str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("aggregator search failed source=%s", source)
        return api_error(50000, msg="aggregator search failed", http_status=500)
    return api_response(data={
        "source": source, "keyword": keyword, "page": page, "items": items or [],
    })


@aggregator_bp.route('/aggregator/detail', methods=['GET'])
def aggregator_detail():
    link = (request.args.get('link') or '').strip()
    if not link:
        return api_error(40000, msg="link required")
    if len(link) > MAX_LINK_LENGTH:
        return api_error(40000, msg=f"link must be at most {MAX_LINK_LENGTH} characters")
    source, error = _request_source()
    if error:
        return error
    try:
        detail = get_detail(link, source=source, proxy=_proxy_for(source))
    except SourceBusyError:
        return api_error(42900, msg="aggregator source is busy", http_status=429)
    except ValueError as exc:
        return api_error(40000, msg=str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("aggregator detail failed source=%s", source)
        return api_error(50000, msg="aggregator detail failed", http_status=500)
    return api_response(data={"source": source, "link": link, "detail": detail})


@aggregator_bp.route('/aggregator/magnet', methods=['GET'])
def aggregator_magnet():
    link = (request.args.get('link') or '').strip()
    if not link:
        return api_error(40000, msg="link required")
    if len(link) > MAX_LINK_LENGTH:
        return api_error(40000, msg=f"link must be at most {MAX_LINK_LENGTH} characters")
    source, error = _request_source()
    if error:
        return error
    try:
        magnet = get_magnet(link, source=source, proxy=_proxy_for(source))
    except SourceBusyError:
        return api_error(42900, msg="aggregator source is busy", http_status=429)
    except ValueError as exc:
        return api_error(40000, msg=str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("aggregator magnet failed source=%s", source)
        return api_error(50000, msg="aggregator magnet failed", http_status=500)
    return api_response(data={"source": source, "link": link, "magnet": magnet})
