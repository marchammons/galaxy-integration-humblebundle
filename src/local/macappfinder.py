import pathlib
from typing import Dict, Set

from local.localgame import LocalHumbleGame
from local.baseappfinder import BaseAppFinder


class MacAppFinder(BaseAppFinder):
    async def find_local_games(self, owned_title_id: Dict[str, str], paths: Set[pathlib.Path]) -> Dict[str, LocalHumbleGame]:
        if paths:
            return await super().find_local_games(owned_title_id, paths)
        return {}
