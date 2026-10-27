"""Turn pytest's JUnit XML into GitHub error annotations, one per failed test.

Annotations show on the run page and through the API, so failures can be read
without downloading the full log. Given pytest's log too, a test that hung (and so
wrote no XML) becomes an annotation as well: the thread stacks pytest's
faulthandler_timeout dumped, and the last progress line, which names the file.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CHUNK = 3500  # characters per annotation
MAX_CHUNKS = 6


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def escape_property(text: str) -> str:
    return escape(text).replace(":", "%3A").replace(",", "%2C")


def failures(path: Path) -> None:
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        for problem in list(case.findall("failure")) + list(case.findall("error")):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            detail = (problem.get("message") or "") + "\n" + (problem.text or "")
            tail = detail.strip()[-CHUNK:]  # the end of a traceback says the most
            print(f"::error title={escape_property(name)}::{escape(tail)}")


def hangs(path: Path) -> None:
    """faulthandler's last "Timeout (0:05:00)!" dump (a slow test may have made one
    earlier), with where the run had got to."""
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.rfind("Timeout (")
    if start < 0:
        return
    before = text[:start].splitlines()
    progress = [line for line in before if re.match(r"tests[\\/]\S+\.py ", line)]
    where = progress[-1][:300] if progress else "(no progress line)"
    dump = text[start:]
    chunks = [dump[i : i + CHUNK] for i in range(0, len(dump), CHUNK)][:MAX_CHUNKS]
    for i, chunk in enumerate(chunks, 1):
        title = f"a test hung ({i}/{len(chunks)}) after: {where}"
        print(f"::error title={escape_property(title)}::{escape(chunk)}")


def main(xml: str, log: str | None = None) -> None:
    if Path(xml).is_file():
        failures(Path(xml))
    if log and Path(log).is_file():
        hangs(Path(log))


if __name__ == "__main__":
    main(*sys.argv[1:3])
