import pathlib
import logging
import toml
import os
from typing import Any, Dict, Callable, Mapping, List

from consts import SOURCES


# in case config entry is removed
DEFAULT_CONFIG = {
    'sources': ['library', 'trove', 'keys'],
    'show_revealed_key_games': False
}


class Settings:
    def __init__(self, config_dir: str, current_version: str, cached_version: str,
                 cached_config: str, save_cache_callback: Callable):
        self._curr_ver = current_version
        self._prev_ver = cached_version
        self._save_cache = save_cache_callback

        self._config: Dict[str, Any] = {}
        self._last_modification_time = None

        self._local_config_file = pathlib.Path(config_dir) / 'config.toml'
        self._cached_config = toml.loads(cached_config)

        self.reload_local_config_if_changed()

    def _load_content(self):
        config_sources = self._config.get('sources', DEFAULT_CONFIG['sources'])
        self._sources = [SOURCES.match(s) for s in config_sources]

    @property
    def sources(self) -> List[SOURCES]:
        return self._sources

    @staticmethod
    def _load_config_file(config_path: pathlib.Path) -> Mapping[str, Any]:
        try:
            with open(config_path, 'r') as f:
                return toml.load(f)
        except Exception as e:
            logging.error('Parsing config file has failed. Default values will be used. Details:' + repr(e))
            return {}

    def _update_user_config(self):
        """Simple migrations"""
        logging.info(f'Recreating user config file with new entries')
        data = toml.dumps(self._config)
        with open(self._local_config_file, 'r') as f:
            comment = ''
            for line in f.readline():
                comment += line
                if line == '# ===':
                    break
        with open(self._local_config_file, 'w') as f:
            f.write(comment)
            f.write(data)

    def reload_local_config_if_changed(self):
        path = self._local_config_file
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            raise
        except Exception as e:
            logging.exception(f'Stating {path} has failed: {str(e)}')
        else:
            if stat.st_mtime == self._last_modification_time:
                return

        local_config = self._load_config_file(self._local_config_file)

        if self._last_modification_time is None:  # first run
            if self._prev_ver is None or self._curr_ver <= self._prev_ver:
                self._config = {**self._cached_config, **local_config}
            else: # prioritize cached config in case of plugin update
                self._config = {**local_config, **self._cached_config}
                self._save_cache('version', self._curr_ver)
                if self._config.keys() - local_config.keys():
                    self._update_user_config()
        else:
            self._config.update(local_config)

        self._load_content()
        self._last_modification_time = stat.st_mtime
        self._save_cache('config', toml.dumps(self._config))