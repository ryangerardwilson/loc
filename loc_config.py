from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


CONFIG_BOOTSTRAP_TEXT = '{\n  "aliases": {}\n}\n'
_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ConfigError(ValueError):
    """Raised when the loc config is missing or invalid."""


@dataclass(frozen=True)
class AliasConfig:
    name: str
    token: str


@dataclass
class LocConfig:
    aliases: dict[str, AliasConfig]


def config_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return root / "loc" / "config.json"


def load_config() -> LocConfig:
    path = config_path()
    if not path.exists():
        return LocConfig(aliases={})

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Config root must be a JSON object")

    raw_aliases = data.get("aliases", {})
    if raw_aliases is None:
        raw_aliases = {}
    if not isinstance(raw_aliases, dict):
        raise ConfigError("'aliases' must be a JSON object")

    aliases: dict[str, AliasConfig] = {}
    for raw_name, raw_value in raw_aliases.items():
        if not isinstance(raw_name, str):
            raise ConfigError("Alias names must be strings")
        name = normalize_alias(raw_name)
        token = _extract_token(name, raw_value)
        aliases[name] = AliasConfig(name=name, token=token)

    return LocConfig(aliases=aliases)


def save_alias(alias: str, token: str) -> Path:
    name = normalize_alias(alias)
    clean_token = normalize_token(token)
    config = load_config()
    config.aliases[name] = AliasConfig(name=name, token=clean_token)
    return write_config(config)


def write_config(config: LocConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "aliases": {
            name: {"token": alias.token}
            for name, alias in sorted(config.aliases.items())
        }
    }
    encoded = json.dumps(payload, indent=2) + "\n"

    tmp_path = path.parent / f"{path.name}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(encoded)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
    return path


def normalize_alias(alias: str) -> str:
    clean = alias.strip()
    if not clean:
        raise ConfigError("Alias cannot be empty")
    if not _ALIAS_PATTERN.fullmatch(clean):
        raise ConfigError("Alias must use letters, numbers, '.', '_' or '-' only")
    return clean


def normalize_token(token: str) -> str:
    clean = token.strip()
    if not clean:
        raise ConfigError("Token cannot be empty")
    return clean


def _extract_token(alias: str, raw_value: object) -> str:
    if isinstance(raw_value, str):
        return normalize_token(raw_value)
    if not isinstance(raw_value, dict):
        raise ConfigError(f"Alias '{alias}' must be a token string or object")

    token = raw_value.get("token")
    if not isinstance(token, str):
        raise ConfigError(f"Alias '{alias}' must define a string token")
    return normalize_token(token)
