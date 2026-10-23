"""Public entry points for the Papermoon rule core.

The existing rule packages remain the single implementation. Importing this
facade starts neither a game nor an editor.
"""

from game.character import create_character_from_card, list_character_cards
from game.game.game_loop import GameLoop
from game.game.game_manager import GameManager
from game.game.game_session import GameSession

__all__ = ["GameManager", "GameLoop", "GameSession", "create_character_from_card", "list_character_cards"]
