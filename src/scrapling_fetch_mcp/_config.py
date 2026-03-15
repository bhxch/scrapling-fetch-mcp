"""Global configuration for scrapling-fetch-mcp"""

from os import getenv

# Mode hierarchy: basic < stealth < max-stealth
MODE_LEVELS = {
    "basic": 0,
    "stealth": 1,
    "max-stealth": 2,
}


class Config:
    """Global configuration singleton"""

    _instance = None
    _min_mode: str = "basic"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def min_mode(self) -> str:
        """Get the minimum mode level"""
        return self._min_mode

    def set_min_mode(self, mode: str) -> None:
        """Set the minimum mode level from CLI or environment"""
        if mode not in MODE_LEVELS:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of: {list(MODE_LEVELS.keys())}"
            )
        self._min_mode = mode

    def get_effective_mode(self, requested_mode: str) -> str:
        """
        Get the effective mode by comparing requested mode with minimum mode.
        Returns the higher of the two modes.
        """
        if requested_mode not in MODE_LEVELS:
            raise ValueError(
                f"Invalid mode '{requested_mode}'. Must be one of: {list(MODE_LEVELS.keys())}"
            )

        requested_level = MODE_LEVELS[requested_mode]
        min_level = MODE_LEVELS[self._min_mode]

        # Return the higher mode
        if requested_level >= min_level:
            return requested_mode
        else:
            return self._min_mode


# Global config instance
config = Config()


def init_config_from_env() -> None:
    """Initialize configuration from environment variables"""
    env_min_mode = getenv("SCRAPLING_MIN_MODE", "").lower()
    if env_min_mode and env_min_mode in MODE_LEVELS:
        config.set_min_mode(env_min_mode)
