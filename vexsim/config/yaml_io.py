"""YAML reading with fixes for PyYAML behavior that silently corrupts robot configs.

* YAML 1.1 reads ``36:48`` as the base-60 integer 2208. Gear ratios are written
  exactly like that, so scalars containing ``:`` stay strings.
* PyYAML keeps the last of two duplicate keys without complaint. A duplicate is
  almost always a copy-paste mistake, so it is an error here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError

from vexsim.config.issues import ConfigError, ConfigIssue

_MERGE_TAG = "tag:yaml.org,2002:merge"


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            seen: set[Any] = set()
            for key_node, _ in node.value:
                if key_node.tag == _MERGE_TAG:
                    continue  # keys merged in with << may be overridden explicitly
                key = self.construct_object(key_node, deep=True)
                try:
                    duplicate = key in seen
                except TypeError:
                    continue  # unhashable key; the base constructor reports it
                if duplicate:
                    raise ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _construct_int(loader: StrictLoader, node: yaml.ScalarNode) -> int | str:
    if ":" in loader.construct_scalar(node):
        return loader.construct_scalar(node)
    return yaml.SafeLoader.construct_yaml_int(loader, node)


def _construct_float(loader: StrictLoader, node: yaml.ScalarNode) -> float | str:
    if ":" in loader.construct_scalar(node):
        return loader.construct_scalar(node)
    return yaml.SafeLoader.construct_yaml_float(loader, node)


StrictLoader.add_constructor("tag:yaml.org,2002:int", _construct_int)
StrictLoader.add_constructor("tag:yaml.org,2002:float", _construct_float)


def parse_yaml(text: str) -> Any:
    return yaml.load(text, Loader=StrictLoader)  # StrictLoader subclasses SafeLoader


def load_yaml_file(path: str | Path) -> Any:
    """Read a YAML file. Raises ConfigError with a line/column location on failure."""
    path = Path(path)
    source = str(path)

    def fail(message: str, location: str = "") -> ConfigError:
        return ConfigError(source, [ConfigIssue("error", location, message)])

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise fail("file not found") from None
    except UnicodeDecodeError as exc:
        raise fail(f"file is not valid UTF-8 ({exc.reason})") from None
    except OSError as exc:
        raise fail(f"cannot read file: {exc.strerror or exc}") from None

    try:
        data = parse_yaml(text)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        location = f"line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = exc.problem or exc.context or "invalid YAML"
        raise fail(problem, location) from None
    except yaml.YAMLError as exc:
        raise fail(f"invalid YAML: {exc}") from None

    if data is None:
        raise fail("file is empty")
    return data
