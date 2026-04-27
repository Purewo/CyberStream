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
        self.re_leading_number = re.compile(r'^(\d{1,4})[\s\.]+')
        self.re_episode_token = re.compile(r'(?i)S\d{1,2}[.\s_-]*E\d{1,3}|(?:E|EP|第)\s*\d+(?:集)?')
        self.re_year = re.compile(r'(?:19|20)\d{2}')
        self.re_noise = re.compile(
            r'(?i)\b(?:'
            r'2160p|1080p|720p|480p|4k|5k|8k|HD|UHD|FHD|'
            r'HEVC|AVC|H\.?264|H\.?265|X264|X265|VC1|VP9|AV1|'
            r'HDR\d*|DOLBY|VISION|ATMOS|TRUEHD|DTS-?X?|DTS-?HD|MA|HD-?MA|AAC|AC3|E-?AC3|DDP\d*|'
            r'[57]\.1|[257]\.0|'
            r'\d{1,2}bit|SDR|'
            r'BLURAY|REMUX|WEB-?DL|WEBRIP|HDTV|BD|'
            r'PROPER|REPACK|EXTENDED|UNRATED|DIRECTORS?|CUT|'
            r'MULTI|COMPLETE|INTERNAL|'
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

    def clean_title_from_filename(self, filename):
        name = (filename or '').rsplit('.', 1)[0]
        name = self.re_episode_token.sub(' ', name)
        name = re.sub(r'^\d+[\s\.]+', '', name)
        return self.clean_name(name)

    def extract_season_episode(self, filename):
        m1 = self.re_s_e.search(filename)
        if m1:
            return int(m1.group(1)), int(m1.group(2))

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
            '高码率', 'HIGH BITRATE', '60FPS', '120FPS', 'HQ', 'EXTRAS', 'SPECIALS', 'FEATURETTES'
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

            season_match = self.re_season_folder.match(parent)
            season_num = 1
            if season_match:
                season_group = season_match.group(1)
                if season_group.isdigit():
                    season_num = int(season_group)

            return ParsedMediaInfo(
                title=title,
                year=year,
                season=season if season is not None else season_num,
                episode=episode,
                media_type_hint='tv',
                parse_layer='strict',
                parse_strategy='season_folder',
                confidence='high',
            )

        mixed_match = self.re_mixed_season_folder.match(parent)
        if mixed_match:
            raw_title = mixed_match.group(1)
            title = self.clean_name(raw_title)
            if title and not self.is_garbage_title(title):
                season_part = mixed_match.group(2)
                season_num = int(season_part) if season_part.isdigit() else 1
                return ParsedMediaInfo(
                    title=title,
                    year=self.extract_year(parent) or self.extract_year(grandparent),
                    season=season if season is not None else season_num,
                    episode=episode,
                    media_type_hint='tv',
                    parse_layer='strict',
                    parse_strategy='mixed_season_folder',
                    confidence='high',
                )

        if season is not None and episode is not None:
            clean_parent = re.sub(r'(?i)S(?:eason)?\s*\d+', '', parent).strip()
            clean_parent = self.clean_name(clean_parent)
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

            filename_title = self.clean_title_from_filename(filename)
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

            season_match = self.re_season_folder.match(parent)
            season_num = 1
            if season_match:
                season_group = season_match.group(1)
                if season_group.isdigit():
                    season_num = int(season_group)

            return ParsedMediaInfo(
                title=title,
                year=year,
                season=season if season is not None else season_num,
                episode=episode,
                media_type_hint='tv',
                parse_layer='fallback',
                parse_strategy='season_folder_heuristic',
                confidence='medium',
            )

        mixed_match = self.re_mixed_season_folder.match(parent)
        if mixed_match:
            raw_title = mixed_match.group(1)
            title = self.clean_name(raw_title)
            season_part = mixed_match.group(2)
            season_num = int(season_part) if season_part.isdigit() else 1
            return ParsedMediaInfo(
                title=title,
                year=self.extract_year(parent) or self.extract_year(grandparent),
                season=season if season is not None else season_num,
                episode=episode,
                media_type_hint='tv',
                parse_layer='fallback',
                parse_strategy='mixed_season_folder_heuristic',
                confidence='medium',
            )

        if season is not None and episode is not None:
            clean_parent = re.sub(r'(?i)S(?:eason)?\s*\d+', '', parent).strip()
            clean_parent = self.clean_name(clean_parent)

            if len(clean_parent) > 1 and not self.is_generic_folder(parent):
                title = clean_parent
                year = self.extract_year(parent)
            else:
                title = self.clean_title_from_filename(filename)
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
            media_type_hint='tv' if episode is not None else 'movie',
            parse_layer='fallback',
            parse_strategy='movie_filename_heuristic',
            confidence='low',
        )
