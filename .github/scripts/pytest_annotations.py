"""Turn pytest's JUnit XML into GitHub error annotations, one per failed test.

Annotations show on the run page and through the API, so failures can be read
without downloading the full log.
"""

import sys
import xml.etree.ElementTree as ET


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def escape_property(text: str) -> str:
    return escape(text).replace(":", "%3A").replace(",", "%2C")


def main(path: str) -> None:
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        for problem in list(case.findall("failure")) + list(case.findall("error")):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            detail = (problem.get("message") or "") + "\n" + (problem.text or "")
            tail = detail.strip()[-3500:]  # the end of a traceback says the most
            print(f"::error title={escape_property(name)}::{escape(tail)}")


if __name__ == "__main__":
    main(sys.argv[1])
