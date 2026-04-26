import logging

from .types import ParsedMediaInfo

logger = logging.getLogger(__name__)


class AIMetadataScraper:
    """AI 元数据层预留实现。

    当前阶段只提供统一入口和明确日志，不实际接入模型。
    后续无论接 OpenAI、本地模型还是其他服务，都应只改这里。
    """

    def resolve(self, parsed_info: ParsedMediaInfo):
        logger.info(
            "Metadata AI layer skipped title=%r year=%s reason=not_enabled",
            parsed_info.title,
            parsed_info.year,
        )
        return None
