import hashlib
import logging
import re
import time
from .types import ParsedMediaInfo

logger = logging.getLogger(__name__)


class PathMetadataParser:
    """三层解析中的前两层：

    1. strict: 面向规范命名结构的高置信解析
    2. fallback: 复用历史经验规则做兜底

    AI 层暂时只预留接口，不在这里直接接入。
    """

    def __init__(self):
        self.re_season_folder = re.compile(
            r'(?i)^(?:Season|S|第)\s*(\d+|[一二三四五六七八九十]+)(?:[\s\._\-]*(?:季|Part|Vol|Chapter|精编版|电影版|Total|End|Fin|版|篇))?.*$'
        )
        self.re_mixed_season_folder = re.compile(
            r'(?i)^(.+?)(?:[\s._-]+|(?=S)|(?=第)|(?=\d))(?:S|Season|第)\s*(\d+|[一二三四五六七八九十]+)(?:季|Season)?(?:$|[\s._\-\[])'
        )
        self.re_episode = re.compile(r'(?i)(?:E|EP|第)\s*(\d+)(?:集)?(?=[\s._\-]|$)')
        self.re_s_e = re.compile(r'(?i)S(\d+)[.\s_-]*E(\d+)')
        self.re_inline_chinese_season_episode = re.compile(
            r'(?i)^(?P<title>.+?)(?<!\d)(?:[\s._\-]*第\s*)?'
            r'(?P<season>\d{1,2}|[一二三四五六七八九十]{1,3})'
            r'(?:\s*(?:季|Season|S))?[\s._\-]*第\s*'
            r'(?P<episode>\d{1,3})\s*[集话話]?(?:\s*(?:END|完结))?$'
        )
        self.re_leading_number = re.compile(r'^(\d{1,4})[\s\.]+')
        self.re_episode_token = re.compile(r'(?i)S\d{1,2}[.\s_-]*E\d{1,3}|(?:E|EP|第)\s*\d+(?:集)?')
        self.re_year = re.compile(r'(?:19|20)\d{2}')
        self.re_noise = re.compile(
            r'(?i)\b(?:'
            r'2160p|1080p|720p|480p|4k|5k|8k|HD|UHD|FHD|'
            r'HEVC|AVC|H\.?264|H\.?265|X264|X265|VC1|VP9|AV1|'
            r'HDR\d*|DV|DOVI|DOLBY|VISION|ATMOS|TRUEHD|DTS-?X?|DTS-?HD|MA|HD-?MA|AAC|AC3|E-?AC3|DDP\d(?:\.\d)?|DDP\d*|H|'
            r'[57]\.1|[257]\.0|'
            r'\d{1,2}bit|SDR|'
            r'BLURAY|REMUX|WEB-?DL|WEBRIP|HDTV|BD|'
            r'PROPER|REPACK|EXTENDED|UNRATED|DIRECTORS?|CUT|'
            r'MULTI|COMPLETE|INTERNAL|ATVP|AMZN|DSNP|NF|'
            r'SWTYBLZ|FGT|OMFUG|DREAMHD|EPSiLON|SPARKS|RARBG|'
            r'HQ|FPS\d*|60FPS|120FPS|\d+FPS|HIGH BITRATE|'
            r'MP4|MKV|AVI|'
            r'日|粤|国|英|中|韩'
            r')\b'
        )

    def generate_stable_id(self, title, year):
        raw = f"{(title or '').strip().lower()}|{year}"
        return "loc-" + hashlib.md5(raw.encode()).hexdigest()[:12]

    def parse(self, file_path):
        strict_result = self._parse_strict(file_path)
        if strict_result:
            return strict_result
        return self._parse_fallback(file_path)

    def build_orphan_fallback(self, title):
        stable_id = self.generate_stable_id(title, 0)
        return {
            "tmdb_id": stable_id,
            "title": "Unknown Series",
            "original_title": title,
            "year": 2077,
            "rating": 0,
            "description": "Auto-grouped orphan files. Please rename folders.",
            "cover": "",
            "background_cover": "",
            "category": ["Misc"],
            "director": "Scanner",
            "actors": [],
            "country": "Local",
            "media_type_hint": "tv",
            "scraper_source": "LOCAL_ORPHAN",
            "scrape_layer": "fallback",
            "scrape_strategy": "orphan_group",
        }

    def build_local_fallback(self, title, year):
        stable_loc_id = self.generate_stable_id(title, year or 2077)
        return {
            "tmdb_id": stable_loc_id,
            "title": title,
            "original_title": title,
            "year": year or 2077,
            "rating": 0,
            "description": "Unidentified (Local)",
            "cover": "",
            "background_cover": "",
            "category": ["Local"],
            "director": "Unknown",
            "actors": [],
            "country": "Unknown",
            "media_type_hint": "movie",
            "scraper_source": "LOCAL_FALLBACK",
            "scrape_layer": "fallback",
            "scrape_strategy": "local_placeholder",
        }

    def clean_name(self, text):
        if not text:
            return ""
        text = self.re_year.sub('', text)
        text = re.sub(r'(?i)(?:Season|S|第)\s*(\d+|[一二三四五六七八九十]+)(?:季|Part|Vol)?', ' ', text)
        text = self.re_noise.sub('', text)
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\(.*?\)', '', text)
        text = re.sub(r'[._\-]+', ' ', text).strip()
        return text

    def parse_number_token(self, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)

        numbers = {
            '零': 0,
            '一': 1,
            '二': 2,
            '两': 2,
            '三': 3,
            '四': 4,
            '五': 5,
            '六': 6,
            '七': 7,
            '八': 8,
            '九': 9,
        }
        if text == '十':
            return 10
        if '十' in text:
            left, right = text.split('十', 1)
            tens = numbers.get(left, 1) if left else 1
            ones = numbers.get(right, 0) if right else 0
            return tens * 10 + ones
        return numbers.get(text)

    def season_number_from_match(self, match, group_index=1):
        if not match:
            return None
        season = self.parse_number_token(match.group(group_index))
        return season if season and season > 0 else None

    def strip_filename_prefix_noise(self, text):
        text = (text or '').rsplit('.', 1)[0].strip()
        text = re.sub(r'^\[[^\]]+\]\s*', ' ', text).strip()
        text = re.sub(r'^【[^】]+】\s*', ' ', text).strip()
        return text

    def extract_inline_chinese_season_episode(self, filename):
        base_name = self.strip_filename_prefix_noise(filename)
        match = self.re_inline_chinese_season_episode.match(base_name)
        if not match:
            return None

        title = self.clean_name(match.group('title'))
        season = self.parse_number_token(match.group('season'))
        episode = self.parse_number_token(match.group('episode'))
        if self.is_garbage_title(title) or season is None or episode is None:
            return None
        return {
            "title": title,
            "season": season,
            "episode": episode,
        }

    def clean_title_from_filename(self, filename):
        inline = self.extract_inline_chinese_season_episode(filename)
        if inline:
            return inline["title"]

        name = (filename or '').rsplit('.', 1)[0]
        name = self.re_episode_token.sub(' ', name)
        name = re.sub(r'^\d+[\s\.]+', '', name)
        return self.clean_name(name)

    def extract_season_episode(self, filename):
        m1 = self.re_s_e.search(filename)
        if m1:
            return int(m1.group(1)), int(m1.group(2))

        inline = self.extract_inline_chinese_season_episode(filename)
        if inline:
            return inline["season"], inline["episode"]

        m2 = self.re_episode.search(filename)
        if m2:
            return None, int(m2.group(1))

        m3 = self.re_leading_number.match(filename)
        if m3:
            num = int(m3.group(1))
            if not (1900 < num < 2100):
                return None, num

        return None, None

    def extract_year(self, text):
        if not text:
            return None
        match = self.re_year.search(text)
        return int(match.group(0)) if match else None

    def is_garbage_title(self, title):
        if not title:
            return True
        if self.is_season_folder(title):
            return True
        if len(title) < 2 and not re.search(r'[\u4e00-\u9fa5]', title):
            return True
        return False

    def is_generic_folder(self, folder_name):
        generic = [
            'DOWNLOAD', 'MOVIE', 'FILM', 'VIDEO', '我的视频', 'DOWNLOADS', 'ANIME', 'TV', 'COLLECTION', 'PUBLIC', 'DAV',
            '高码率', 'HIGH BITRATE', '60FPS', '120FPS', 'HQ', 'EXTRAS', 'SPECIALS', 'FEATURETTES',
            '未分类', '独立资源',
        ]
        u_name = (folder_name or '').upper()
        if u_name in generic:
            return True
        if '高码率' in u_name or 'HIGH BITRATE' in u_name:
            return True
        return False

    def is_season_folder(self, folder_name):
        if not folder_name:
            return False
        if self.re_season_folder.match(folder_name):
            return True
        if re.match(r'^第[一二三四五六七八九十]+季.*$', folder_name):
            return True
        return False

    def optimize_entities(self, raw_entities):
        optimized = {}

        for key, files in raw_entities.items():
            title, year = key
            clean_title = self.clean_name(title)

            if self.is_garbage_title(clean_title):
                sample_file = files[0]
                inferred = self.clean_title_from_filename(sample_file['name'])

                if inferred and len(inferred) > 1 and not self.is_garbage_title(inferred):
                    logger.info("Metadata parser fixed garbage title original=%r inferred=%r", title, inferred)
                    clean_title = inferred
                else:
                    logger.warning("Metadata parser failed to recover title original=%r", title)
                    clean_title = f"UNKNOWN_SHOW_{int(time.time())}"
                    year = None

            new_key = (clean_title, year)
            optimized.setdefault(new_key, [])
            optimized[new_key].extend(files)

            for item in files:
                item['_meta']['title'] = clean_title
                item['_meta']['year'] = year

        return optimized

    def _parse_strict(self, file_path):
        file_path = file_path.replace('\\', '/')
        path_parts = file_path.strip('/').split('/')
        filename = path_parts[-1]
        parent = path_parts[-2] if len(path_parts) > 1 else ""
        grandparent = path_parts[-3] if len(path_parts) > 2 else ""
        great_grandparent = path_parts[-4] if len(path_parts) > 3 else ""

        season, episode = self.extract_season_episode(filename)
        file_year = self.extract_year(filename)
        inline = self.extract_inline_chinese_season_episode(filename)
        if inline:
            return ParsedMediaInfo(
                title=inline["title"],
                year=file_year,
                season=inline["season"],
                episode=inline["episode"],
                media_type_hint='tv',
                parse_layer='strict',
                parse_strategy='inline_chinese_season_episode',
                confidence='high',
            )

        parent_is_season = self.is_season_folder(parent)
        grandparent_is_season = self.is_season_folder(grandparent)

        if parent_is_season:
            title_candidate_folder = grandparent
            if grandparent_is_season or not title_candidate_folder:
                title_candidate_folder = great_grandparent

            title = self.clean_name(title_candidate_folder)
            year = self.extract_year(title_candidate_folder)
            if not title or self.is_generic_folder(title) or self.is_garbage_title(title):
                return None

            season_num = self.season_number_from_match(self.re_season_folder.match(parent)) or 1
            season_conflict = season is not None and season != season_num

            return ParsedMediaInfo(
                title=title,
                year=year,
                season=season_num,
                episode=episode,
                media_type_hint='tv',
                parse_layer='strict',
                parse_strategy='season_folder',
                confidence='medium' if season_conflict else 'high',
                extras={"season_source": "folder", "filename_season": season} if season_conflict else {},
            )

        mixed_match = self.re_mixed_season_folder.match(parent)
        if mixed_match:
            raw_title = mixed_match.group(1)
            title = self.clean_name(raw_title)
            if title and not self.is_garbage_title(title):
                season_num = self.season_number_from_match(mixed_match, 2) or 1
                season_conflict = season is not None and season != season_num
                return ParsedMediaInfo(
                    title=title,
                    year=self.extract_year(parent) or self.extract_year(grandparent),
                    season=season_num,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='mixed_season_folder',
                    confidence='medium' if season_conflict else 'high',
                    extras={"season_source": "folder", "filename_season": season} if season_conflict else {},
                )

        if season is not None and episode is not None:
            clean_parent = re.sub(r'(?i)S(?:eason)?\s*\d+', '', parent).strip()
            clean_parent = self.clean_name(clean_parent)
            filename_title = self.clean_title_from_filename(filename)
            parent_looks_like_season_alias = bool(re.search(r'(?<!\d)\d{1,2}$', clean_parent or ''))
            if (
                parent_looks_like_season_alias
                and filename_title
                and not self.is_garbage_title(filename_title)
            ):
                return ParsedMediaInfo(
                    title=filename_title,
                    year=file_year,
                    season=season,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='flat_sxxexx_filename',
                    confidence='high',
                )
            if clean_parent and len(clean_parent) > 1 and not self.is_generic_folder(parent):
                return ParsedMediaInfo(
                    title=clean_parent,
                    year=self.extract_year(parent),
                    season=season,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='flat_sxxexx',
                    confidence='high',
                )

            if filename_title and not self.is_garbage_title(filename_title):
                return ParsedMediaInfo(
                    title=filename_title,
                    year=file_year,
                    season=season,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='flat_sxxexx_filename',
                    confidence='high',
                )

        if episode is not None:
            filename_title = self.clean_title_from_filename(filename)
            if filename_title and not self.is_garbage_title(filename_title):
                return ParsedMediaInfo(
                    title=filename_title,
                    year=file_year,
                    season=season,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='episode_only_filename',
                    confidence='medium',
                )

        if episode is not None and parent and not self.is_generic_folder(parent):
            clean_parent = self.clean_name(parent)
            if clean_parent and not self.is_garbage_title(clean_parent):
                return ParsedMediaInfo(
                    title=clean_parent,
                    year=self.extract_year(parent) or self.extract_year(grandparent),
                    season=season,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='episode_only_parent_folder',
                    confidence='medium',
                )

        clean_parent = self.clean_name(parent)
        if not self.is_generic_folder(parent) and len(clean_parent) > 1 and season is None and episode is None:
            return ParsedMediaInfo(
                title=clean_parent,
                year=self.extract_year(parent),
                media_type_hint='movie',
                parse_layer='strict',
                parse_strategy='movie_parent_folder',
                confidence='high',
            )

        if file_year and season is None and episode is None:
            clean_filename = self.clean_title_from_filename(filename)
            if clean_filename and not self.is_garbage_title(clean_filename):
                return ParsedMediaInfo(
                    title=clean_filename,
                    year=file_year,
                    media_type_hint='movie',
                    parse_layer='strict',
                    parse_strategy='movie_filename_with_year',
                    confidence='medium',
                )

        return None

    def _parse_fallback(self, file_path):
        file_path = file_path.replace('\\', '/')
        path_parts = file_path.strip('/').split('/')
        filename = path_parts[-1]
        parent = path_parts[-2] if len(path_parts) > 1 else ""
        grandparent = path_parts[-3] if len(path_parts) > 2 else ""
        great_grandparent = path_parts[-4] if len(path_parts) > 3 else ""

        season, episode = self.extract_season_episode(filename)
        file_year = self.extract_year(filename)
        inline = self.extract_inline_chinese_season_episode(filename)
        if inline:
            return ParsedMediaInfo(
                title=inline["title"],
                year=file_year,
                season=inline["season"],
                episode=inline["episode"],
                media_type_hint='tv',
                parse_layer='fallback',
                parse_strategy='inline_chinese_season_episode_heuristic',
                confidence='medium',
            )
        parent_is_season = self.is_season_folder(parent)
        grandparent_is_season = self.is_season_folder(grandparent)

        if parent_is_season:
            title_candidate_folder = grandparent
            if grandparent_is_season or not title_candidate_folder:
                title_candidate_folder = great_grandparent

            title = self.clean_name(title_candidate_folder)
            year = self.extract_year(title_candidate_folder)

            if not title or self.is_generic_folder(title) or self.is_garbage_title(title):
                name_base = filename.split('S')[0] if 'S' in filename else filename
                name_base = re.sub(r'^\d+[\s\.]+', '', name_base)
                title = self.clean_name(name_base)

            season_num = self.season_number_from_match(self.re_season_folder.match(parent)) or 1
            season_conflict = season is not None and season != season_num

            return ParsedMediaInfo(
                title=title,
                year=year,
                season=season_num,
                episode=episode,
                media_type_hint='tv',
                parse_layer='fallback',
                parse_strategy='season_folder_heuristic',
                confidence='low' if season_conflict else 'medium',
                extras={"season_source": "folder", "filename_season": season} if season_conflict else {},
            )

        mixed_match = self.re_mixed_season_folder.match(parent)
        if mixed_match:
            raw_title = mixed_match.group(1)
            title = self.clean_name(raw_title)
            season_num = self.season_number_from_match(mixed_match, 2) or 1
            season_conflict = season is not None and season != season_num
            return ParsedMediaInfo(
                title=title,
                year=self.extract_year(parent) or self.extract_year(grandparent),
                season=season_num,
                episode=episode,
                media_type_hint='tv',
                parse_layer='fallback',
                parse_strategy='mixed_season_folder_heuristic',
                confidence='low' if season_conflict else 'medium',
                extras={"season_source": "folder", "filename_season": season} if season_conflict else {},
            )

        if season is not None and episode is not None:
            clean_parent = re.sub(r'(?i)S(?:eason)?\s*\d+', '', parent).strip()
            clean_parent = self.clean_name(clean_parent)
            filename_title = self.clean_title_from_filename(filename)
            parent_looks_like_season_alias = bool(re.search(r'(?<!\d)\d{1,2}$', clean_parent or ''))

            if (
                parent_looks_like_season_alias
                and filename_title
                and not self.is_garbage_title(filename_title)
            ):
                title = filename_title
                year = file_year
            elif len(clean_parent) > 1 and not self.is_generic_folder(parent):
                title = clean_parent
                year = self.extract_year(parent)
            else:
                title = filename_title
                year = file_year

            return ParsedMediaInfo(
                title=title,
                year=year,
                season=season,
                episode=episode,
                media_type_hint='tv',
                parse_layer='fallback',
                parse_strategy='flat_sxxexx_heuristic',
                confidence='medium',
            )

        if episode is not None and parent and not self.is_generic_folder(parent):
            title = self.clean_name(parent)
            if title and not self.is_garbage_title(title):
                return ParsedMediaInfo(
                    title=title,
                    year=self.extract_year(parent) or self.extract_year(grandparent),
                    season=season,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='fallback',
                    parse_strategy='episode_only_parent_folder_heuristic',
                    confidence='medium',
                )

        if self.is_generic_folder(parent):
            title = self.clean_name(grandparent)
            year = self.extract_year(grandparent)
            if not title:
                title = self.clean_title_from_filename(filename)
            return ParsedMediaInfo(
                title=title,
                year=year,
                season=season,
                episode=episode,
                media_type_hint='tv' if episode is not None else 'movie',
                parse_layer='fallback',
                parse_strategy='generic_parent_folder',
                confidence='low',
            )

        clean_parent = self.clean_name(parent)
        clean_filename = self.clean_title_from_filename(filename)
        parent_year = self.extract_year(parent)

        if not self.is_generic_folder(parent) and len(clean_parent) > 1:
            return ParsedMediaInfo(
                title=clean_parent,
                year=parent_year,
                media_type_hint='movie',
                parse_layer='fallback',
                parse_strategy='movie_parent_folder_heuristic',
                confidence='medium',
            )

        return ParsedMediaInfo(
            title=clean_filename,
            year=file_year,
            season=season,
            episode=episode,
            media_type_hint='tv' if episode is not None else 'movie',
            parse_layer='fallback',
            parse_strategy='movie_filename_heuristic',
            confidence='low',
        )
