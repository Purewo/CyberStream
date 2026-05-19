import re
import time
from dataclasses import dataclass

from backend import config


@dataclass
class ParsedPathMetadata:
    title: str
    year: int | None
    season: int | None
    episode: int | None
    parse_mode: str
    parse_strategy: str
    needs_review: bool = False

    def to_dict(self):
        return {
            "title": self.title,
            "year": self.year,
            "season": self.season,
            "episode": self.episode,
            "parse_mode": self.parse_mode,
            "parse_strategy": self.parse_strategy,
            "needs_review": self.needs_review,
        }


class MediaPathCleaner:
    def __init__(self):
        self.standard_movie_patterns = [
            re.compile(r'^(?P<title>.+?)[\s._\-\(\[]+(?P<year>(?:19|20)\d{2})(?:[\s._\-\)\]].*)?$', re.I),
        ]
        self.re_season_folder = re.compile(
            r'(?i)^(?:Season|S|第)\s*(\d+|[一二三四五六七八九十]+)(?:[\s\._\-]*(?:季|Part|Vol|Chapter|精编版|电影版|Total|End|Fin|版|篇))?.*$'
        )
        self.re_mixed_season_folder = re.compile(
            r'(?i)^(.+?)(?:[\s._-]+|(?=S)|(?=第)|(?=\d))(?:S|Season|第)\s*(\d+|[一二三四五六七八九十]+)(?:季|Season)?(?:$|[\s._\-\[])'
        )
        self.re_episode = re.compile(r'(?i)(?:E|EP|第)\s*(\d+)(?:集|\s|$)')
        self.re_s_e = re.compile(r'(?i)S(\d+)[.\s_-]*E(\d+)')
        self.re_inline_chinese_season_episode = re.compile(
            r'(?i)^(?P<title>.+?)(?<!\d)(?:[\s._\-]*第\s*)?'
            r'(?P<season>\d{1,2}|[一二三四五六七八九十]{1,3})'
            r'(?:\s*(?:季|Season|S))?[\s._\-]*第\s*'
            r'(?P<episode>\d{1,3})\s*[集话話]?(?:\s*(?:END|完结))?$'
        )
        self.re_leading_number = re.compile(r'^(\d{1,4})[\s\.]+')
        self.re_year = re.compile(config.REGEX_PATTERNS['year'])
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
        self.re_loose_episode_suffix = re.compile(
            r'(?i)(?:^|[\s._\-])(?:EP?)?\d{1,3}(?:v\d+)?(?:END)?(?:$|[\s._\-])'
        )
        self.re_release_group_episode = re.compile(
            r'(?i)(?:^|[\s._\-])(?P<episode>\d{1,3})(?:v\d+)?(?:END)?(?:$|[\s._\-\[])'
        )
        self.re_audio_channel = re.compile(r'(?<!\d)(?:[257]\.1|[257]\.0)(?!\d)')
        self.re_resolution_pair = re.compile(r'(?<!\d)\d{3,4}[x×]\d{3,4}(?!\d)', re.I)
        self._bracket_noise_tokens = {
            'ANI', 'BAHA', 'B-GLOBAL', 'CR', 'NC-RAWS', 'LILITH-RAWS', 'LOLIHOUSE',
            '1080P', '720P', '2160P', 'HEVC', 'AVC', 'AAC', 'CHT', 'CHS',
        }
        self._generic_folder_tokens = {
            'DOWNLOAD', 'DOWNLOADS', 'MOVIE', 'MOVIES', 'FILM', 'FILMS', 'VIDEO', 'VIDEOS',
            'SHOW', 'SHOWS', 'SERIES', 'TV', 'TVSHOW', 'TVSHOWS', 'ANIME', 'ANIMATION',
            'COLLECTION', 'COLLECTIONS', 'PUBLIC', 'DAV', 'HIGH BITRATE', '60FPS', '120FPS',
            'HQ', 'EXTRAS', 'SPECIALS', 'FEATURETTES',
            '电影', '影片', '影视', '剧集', '电视剧', '连续剧', '动画', '动漫', '番剧', '合集', '资源',
            '我的视频', '高码率', '未分类', '独立资源',
        }

    def _parse_number_token(self, value):
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

    def _season_number_from_match(self, match, group_index=1):
        if not match:
            return None
        season = self._parse_number_token(match.group(group_index))
        return season if season and season > 0 else None

    def _strip_filename_prefix_noise(self, text):
        text = (text or '').rsplit('.', 1)[0].strip()
        text = re.sub(r'^\[[^\]]+\]\s*', ' ', text).strip()
        text = re.sub(r'^【[^】]+】\s*', ' ', text).strip()
        return text

    def _extract_inline_chinese_season_episode(self, filename):
        base_name = self._strip_filename_prefix_noise(filename)
        match = self.re_inline_chinese_season_episode.match(base_name)
        if not match:
            return None

        title = self.clean_name(match.group('title'))
        season = self._parse_number_token(match.group('season'))
        episode = self._parse_number_token(match.group('episode'))
        if self._is_garbage_title(title) or season is None or episode is None:
            return None
        return {
            "title": title,
            "season": season,
            "episode": episode,
        }

    def clean_name(self, text):
        if not text:
            return ""
        text = self.re_resolution_pair.sub(' ', text)
        text = self.re_audio_channel.sub(' ', text)
        text = self.re_s_e.sub(' ', text)
        text = self.re_episode.sub(' ', text)
        text = re.sub(r'(?i)(?:Season|S|第)\s*(\d+|[一二三四五六七八九十]+)(?:季|Part|Vol)?', ' ', text)
        text = self.re_noise.sub('', text)
        text = re.sub(r'(?i)\b(?:TRUEHD|DTS(?:-HD)?|HDMA|ATMOS|DV|HDR|REMUX|WEB(?:-DL)?|BLURAY|UHD|IMAX|REPACK|PROPER)\s*\d+\b', ' ', text)
        text = re.sub(r'\(.*?\)', '', text)
        text = re.sub(r'[\[\]【】]', ' ', text)
        text = re.sub(r'[._\-]+', ' ', text).strip()
        text = re.sub(r'\s+\d{1,3}(?:v\d+)?(?:END)?$', '', text, flags=re.I).strip()
        tokens = [item for item in re.split(r'\s+', text) if item]
        non_year_tokens = [item for item in tokens if not re.fullmatch(r'(?:19|20)\d{2}', item)]
        if non_year_tokens:
            tokens = non_year_tokens
        return ' '.join(tokens)

    def _extract_release_group_episode(self, text):
        if not text:
            return None
        sanitized = self.re_resolution_pair.sub(' ', str(text))
        sanitized = self.re_audio_channel.sub(' ', sanitized)
        match = self.re_release_group_episode.search(sanitized)
        if match:
            return int(match.group('episode'))
        return None

    def extract_season_episode(self, filename):
        m1 = self.re_s_e.search(filename)
        if m1:
            return int(m1.group(1)), int(m1.group(2))

        inline = self._extract_inline_chinese_season_episode(filename)
        if inline:
            return inline["season"], inline["episode"]

        m2 = self.re_episode.search(filename)
        if m2:
            return None, int(m2.group(1))

        m3 = self.re_leading_number.match(filename)
        if m3:
            num = int(m3.group(1))
            title_candidate = self._filename_title_candidate(filename)
            if title_candidate and not (1900 < num < 2100):
                return None, num

        return None, None

    def _extract_numeric_episode_filename(self, filename):
        base_name = re.sub(r'\.[^.]+$', '', filename or '').strip()
        match = re.match(r'(?i)^(?:EP?)?\s*0*(\d{1,3})(?=$|[\s._\-])', base_name)
        if not match:
            return None
        try:
            episode = int(match.group(1))
        except ValueError:
            return None
        if 1 <= episode <= 200:
            return episode
        return None

    def extract_year(self, text):
        if not text:
            return None
        tokens = re.split(r'[\s._\-\(\)\[\]]+', str(text))
        year_tokens = [
            int(item)
            for item in tokens
            if re.fullmatch(r'(?:19|20)\d{2}', item or '')
        ]
        return year_tokens[-1] if year_tokens else None

    def _is_season_folder(self, folder_name):
        if self.re_season_folder.match(folder_name or ''):
            return True
        if re.match(r'^第[一二三四五六七八九十]+季.*$', folder_name or ''):
            return True
        return False

    def _is_garbage_title(self, title):
        if not title:
            return True
        if self._is_season_folder(title):
            return True
        if self._is_generic_folder(title):
            return True
        if len(title) < 2 and not re.search(r'[\u4e00-\u9fa5]', title):
            return True
        return False

    def _is_generic_folder(self, folder_name):
        normalized = self.clean_name(folder_name).upper()
        if not normalized:
            return False
        return normalized in self._generic_folder_tokens

    def _build_result(self, title, year, season, episode, parse_mode, parse_strategy, needs_review=False):
        return ParsedPathMetadata(
            title=title,
            year=year,
            season=season,
            episode=episode,
            parse_mode=parse_mode,
            parse_strategy=parse_strategy,
            needs_review=needs_review,
        )

    def _filename_title_candidate(self, filename):
        inline = self._extract_inline_chinese_season_episode(filename)
        if inline:
            return inline["title"]

        base_name = filename.rsplit('.', 1)[0]
        if re.fullmatch(r'\d{1,4}', base_name.strip()):
            return ""
        base_name = self.re_s_e.sub(' ', base_name)
        base_name = self.re_episode.sub(' ', base_name)
        base_name = self.re_loose_episode_suffix.sub(' ', base_name)
        base_name = re.sub(r'^\d+[\s\.]+', '', base_name)
        return self.clean_name(base_name)

    def _parse_standard_filename(self, filename):
        base_name = filename.rsplit('.', 1)[0]
        base_name = re.sub(r'^\[[^\]]+\]', ' ', base_name).strip()
        base_name = re.sub(r'^【[^】]+】', ' ', base_name).strip()
        base_name = re.sub(r'\[(?:4K|8K|DIY|BDJ|BDMV|菜单|[^\]]*字幕[^\]]*|[^\]]*音轨[^\]]*|[^\]]*配音[^\]]*|[^\]]*特效[^\]]*|[^\]]*帧率[^\]]*|[^\]]*高码[^\]]*)\]', ' ', base_name, flags=re.I)
        season, episode = self.extract_season_episode(base_name)
        if season is not None or episode is not None:
            return None
        for pattern in self.standard_movie_patterns:
            match = pattern.match(base_name)
            if not match:
                continue
            title = self.clean_name(match.group('title'))
            year = self.extract_year(match.group('year'))
            if not self._is_garbage_title(title):
                return self._build_result(title, year, None, None, 'standard', 'movie_filename_year')
        return None

    def _parse_release_group_filename(self, filename):
        base_name = filename.rsplit('.', 1)[0]
        bracket_values = [item.strip() for item in re.findall(r'\[([^\]]+)\]', base_name)]

        bracket_free_base = re.sub(r'\[[^\]]+\]', ' ', base_name)
        release_group_episode = None
        episode_match = self._extract_release_group_episode(bracket_free_base)
        if episode_match is not None:
            release_group_episode = episode_match

        if not bracket_values and release_group_episode is None:
            return None

        candidates = []
        for item in bracket_values:
            if not item:
                continue
            if item.upper() in self._bracket_noise_tokens:
                continue
            if self.re_noise.search(item):
                continue
            if re.fullmatch(r'\d{1,4}', item):
                continue
            cleaned = self.clean_name(item)
            if not self._is_garbage_title(cleaned):
                candidates.append(cleaned)

        bracket_free_title = self._filename_title_candidate(re.sub(r'\[[^\]]+\]', ' ', filename))
        if not self._is_garbage_title(bracket_free_title):
            return self._build_result(
                bracket_free_title,
                self.extract_year(base_name),
                None,
                release_group_episode,
                'fallback',
                'dirty_release_group',
                True,
            )

        if candidates:
            candidates.sort(key=lambda item: (-len(item), item))
            return self._build_result(
                candidates[0],
                self.extract_year(base_name),
                None,
                release_group_episode,
                'fallback',
                'dirty_bracket_title',
                True,
            )

        return None

    def _parse_standard_path(self, file_path):
        file_path = file_path.replace('\\', '/')
        path_parts = file_path.strip('/').split('/')

        filename = path_parts[-1]
        parent = path_parts[-2] if len(path_parts) > 1 else ""
        grandparent = path_parts[-3] if len(path_parts) > 2 else ""
        great_grandparent = path_parts[-4] if len(path_parts) > 3 else ""

        season, episode = self.extract_season_episode(filename)
        file_year = self.extract_year(filename)
        standard_filename = self._parse_standard_filename(filename)
        if standard_filename:
            return standard_filename
        inline = self._extract_inline_chinese_season_episode(filename)
        if inline:
            return self._build_result(
                inline["title"],
                file_year,
                inline["season"],
                inline["episode"],
                'standard',
                'inline_chinese_season_episode',
            )

        parent_is_season = self._is_season_folder(parent)
        grandparent_is_season = self._is_season_folder(grandparent)

        if parent_is_season:
            episode = episode or self._extract_numeric_episode_filename(filename)
            title_candidate_folder = grandparent
            if grandparent_is_season or not title_candidate_folder:
                title_candidate_folder = great_grandparent

            title = self.clean_name(title_candidate_folder)
            year = self.extract_year(title_candidate_folder)
            if self._is_garbage_title(title) or self._is_generic_folder(title):
                title = self._filename_title_candidate(filename)
            if not self._is_garbage_title(title):
                season_num = self._season_number_from_match(self.re_season_folder.match(parent)) or 1
                season_conflict = season is not None and season != season_num
                return self._build_result(
                    title,
                    year,
                    season_num,
                    episode,
                    'standard',
                    'nested_season',
                    needs_review=season_conflict,
                )

        mixed_match = self.re_mixed_season_folder.match(parent)
        if mixed_match:
            title = self.clean_name(mixed_match.group(1))
            if not self._is_garbage_title(title):
                season_num = self._season_number_from_match(mixed_match, 2) or 1
                season_conflict = season is not None and season != season_num
                year = self.extract_year(parent) or self.extract_year(grandparent)
                return self._build_result(
                    title,
                    year,
                    season_num,
                    episode,
                    'standard',
                    'mixed_season_folder',
                    needs_review=season_conflict,
                )

        if season is not None and episode is not None:
            clean_parent = re.sub(r'(?i)S(?:eason)?\s*\d+', '', parent).strip()
            clean_parent = self.clean_name(clean_parent)
            title = self._filename_title_candidate(filename)
            parent_looks_like_season_alias = bool(re.search(r'(?<!\d)\d{1,2}$', clean_parent or ''))
            if (
                parent_looks_like_season_alias
                and not self._is_garbage_title(title)
            ):
                return self._build_result(title, file_year, season, episode, 'standard', 'flat_episode_filename')
            if not self._is_garbage_title(clean_parent) and not self._is_generic_folder(parent):
                return self._build_result(
                    clean_parent,
                    self.extract_year(parent),
                    season,
                    episode,
                    'standard',
                    'flat_episode',
                )

            if not self._is_garbage_title(title):
                return self._build_result(title, file_year, season, episode, 'standard', 'flat_episode_filename')

        if episode is not None:
            title = self._filename_title_candidate(filename)
            if not self._is_garbage_title(title):
                return self._build_result(
                    title,
                    file_year,
                    season,
                    episode,
                    'standard',
                    'episode_only_filename',
                )

            clean_parent = self.clean_name(parent)
            if not self._is_garbage_title(clean_parent) and not self._is_generic_folder(parent):
                return self._build_result(
                    clean_parent,
                    self.extract_year(parent),
                    season,
                    episode,
                    'standard',
                    'episode_only_parent_folder',
                )

        release_group_result = self._parse_release_group_filename(filename)
        if release_group_result:
            release_group_result.season = season if season is not None else release_group_result.season
            release_group_result.episode = episode if episode is not None else release_group_result.episode
            return release_group_result

        clean_parent = self.clean_name(parent)
        if not self._is_generic_folder(parent) and not self._is_garbage_title(clean_parent):
            return self._build_result(
                clean_parent,
                self.extract_year(parent),
                None,
                None,
                'standard',
                'movie_parent',
            )

        return None

    def _candidate_score(self, text, source):
        if not text:
            return None
        score_map = {
            'filename': 90,
            'parent': 80,
            'grandparent': 70,
            'great_grandparent': 60,
        }
        score = score_map.get(source, 50)
        if re.search(r'[\u4e00-\u9fa5]', text):
            score += 5
        if len(text) >= 4:
            score += 3
        return score

    def _parse_fallback_path(self, file_path):
        file_path = file_path.replace('\\', '/')
        path_parts = file_path.strip('/').split('/')

        filename = path_parts[-1]
        parent = path_parts[-2] if len(path_parts) > 1 else ""
        grandparent = path_parts[-3] if len(path_parts) > 2 else ""
        great_grandparent = path_parts[-4] if len(path_parts) > 3 else ""

        season, episode = self.extract_season_episode(filename)
        file_year = self.extract_year(filename)
        release_group_result = self._parse_release_group_filename(filename)
        if release_group_result:
            release_group_result.season = season if season is not None else release_group_result.season
            release_group_result.episode = episode if episode is not None else release_group_result.episode
            return release_group_result

        raw_candidates = [
            ('filename', self._filename_title_candidate(filename), file_year),
            ('parent', self.clean_name(parent), self.extract_year(parent)),
            ('grandparent', self.clean_name(grandparent), self.extract_year(grandparent)),
            ('great_grandparent', self.clean_name(great_grandparent), self.extract_year(great_grandparent)),
        ]

        candidates = []
        for source, title, year in raw_candidates:
            if self._is_garbage_title(title):
                continue
            if source == 'parent' and self._is_generic_folder(parent):
                continue
            if source != 'filename' and self._is_generic_folder(title):
                continue
            score = self._candidate_score(title, source)
            if score is not None:
                candidates.append((score, source, title, year))

        if candidates:
            _, source, title, year = max(candidates, key=lambda item: item[0])
            return self._build_result(
                title=title,
                year=year or file_year,
                season=season,
                episode=episode,
                parse_mode='fallback',
                parse_strategy=f'dirty_{source}',
                needs_review=True,
            )

        fallback_title = self._filename_title_candidate(filename)
        if self._is_garbage_title(fallback_title):
            for folder_name in (parent, grandparent, great_grandparent):
                if self._is_generic_folder(folder_name):
                    continue
                candidate = self.clean_name(folder_name)
                if not self._is_garbage_title(candidate):
                    fallback_title = candidate
                    break
        if self._is_garbage_title(fallback_title):
            fallback_title = "UNKNOWN"
        return self._build_result(
            title=fallback_title,
            year=file_year,
            season=season,
            episode=episode,
            parse_mode='fallback',
            parse_strategy='dirty_unresolved',
            needs_review=True,
        )

    def parse_path_metadata(self, file_path):
        standard_result = self._parse_standard_path(file_path)
        if standard_result:
            return standard_result
        return self._parse_fallback_path(file_path)

    def repair_group_title(self, title, sample_file_path, current_year=None):
        clean_title = self.clean_name(title)
        if not self._is_garbage_title(clean_title):
            return self._build_result(
                title=clean_title,
                year=current_year,
                season=None,
                episode=None,
                parse_mode='standard',
                parse_strategy='group_normalized',
                needs_review=False,
            )

        fallback_result = self._parse_fallback_path(sample_file_path)
        if not self._is_garbage_title(fallback_result.title):
            return self._build_result(
                title=fallback_result.title,
                year=fallback_result.year or current_year,
                season=None,
                episode=None,
                parse_mode='fallback',
                parse_strategy=fallback_result.parse_strategy,
                needs_review=True,
            )

        return self._build_result(
            title=f"UNKNOWN_SHOW_{int(time.time())}",
            year=None,
            season=None,
            episode=None,
            parse_mode='fallback',
            parse_strategy='dirty_unknown',
            needs_review=True,
        )
