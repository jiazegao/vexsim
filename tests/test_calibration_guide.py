"""Phase 14.6: the calibration guide (docs/calibration_guide.md) says what the tools do: its
pictures and links are there, its vexsim commands parse as written, and the screens it quotes
are the calibration program's."""

import re
import shlex

import pytest

from tests.conftest import ROOT
from vexsim.cli import build_parser

DOCS = ROOT / "docs"
GUIDE = DOCS / "calibration_guide.md"
PICTURES = DOCS / "img" / "guide"
PROGRAM = ROOT / "vexsim" / "bridge" / "cpp" / "calibration" / "main.cpp"
TEXT = GUIDE.read_text(encoding="utf-8")


def code_blocks(text: str) -> list[str]:
    return re.findall(r"^[ \t]*```[\w-]*\n(.*?)^[ \t]*```", text, flags=re.M | re.S)


def prose(text: str) -> str:
    """The text without its code blocks."""
    return re.sub(r"^[ \t]*```[\w-]*\n.*?^[ \t]*```", "", text, flags=re.M | re.S)


def slug(heading: str) -> str:
    """A heading's anchor, as GitHub makes it."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(path) -> set[str]:
    text = prose(path.read_text(encoding="utf-8"))
    return {slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, flags=re.M)}


def links(text: str) -> list[str]:
    """Every link and picture's target in the text (not inside code)."""
    return re.findall(r"\]\(([^)\s]+)\)", re.sub(r"`[^`\n]*`", "", prose(text)))


# --- pictures and links ------------------------------------------------------------------------


@pytest.mark.parametrize("document", [GUIDE, PICTURES / "report_example.md"])
def test_every_picture_and_link_is_there(document):
    text = document.read_text(encoding="utf-8")
    missing = []
    for target in links(text):
        if re.match(r"^[a-z]+:", target):  # https: and the like
            continue
        path, _, anchor = target.partition("#")
        file = (document.parent / path).resolve() if path else document
        if not file.exists():
            missing.append(target)
        elif anchor and anchor not in anchors(file):
            missing.append(target)
    assert missing == []


def test_every_picture_made_for_the_guide_is_in_it():
    shown = {(GUIDE.parent / t).resolve() for t in links(TEXT)}
    shown |= {(PICTURES / t).resolve() for t in links((PICTURES / "report_example.md").read_text())}
    unused = [p.name for p in sorted(PICTURES.glob("*.png")) if p.resolve() not in shown]
    assert unused == []


def test_the_readme_points_to_the_guide():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/calibration_guide.md" in readme


# --- commands ----------------------------------------------------------------------------------


def commands() -> list[str]:
    found = []
    for block in code_blocks(TEXT):
        found += [line.strip() for line in block.splitlines() if line.strip().startswith("vexsim ")]
    return found


def words(command: str) -> list[str]:
    return shlex.split(command.replace("\\", "/"))  # a Windows path's \ is no escape


def test_the_guide_writes_out_each_step():
    used = {" ".join(words(c)[1:3]) for c in commands()}
    for step in (
        "doctor",
        "ui",
        "validate-config examples/robots/1239e_2026-27.yaml",
        "calibration program",
        "calibration collect",
        "calibrate examples/robots/1239e_2026-27.yaml",
        "logger add",
        "calibration check-auton",
    ):
        assert any(u.startswith(step) for u in used), step


@pytest.mark.parametrize("command", commands())
def test_each_command_parses_as_written(command):
    argv = words(command)
    try:
        build_parser().parse_args(argv[1:])
    except SystemExit as exc:  # argparse's way to refuse (and --version's to finish)
        assert exc.code == 0, command
    for word in argv:
        if word.startswith("examples/"):
            assert (ROOT / word).exists(), word


# --- the screens -------------------------------------------------------------------------------

SPEC = re.compile(r"%%|%[-+ 0#]*\d*(?:\.\d+)?([sdifc])")
ANY = {"s": ".+", "d": r"-?\d+", "i": r"-?\d+", "f": r"-?\d+(?:\.\d+)?", "c": "."}


def screen_texts() -> list[str]:
    """The program's texts, each as a pattern of what it shows (its printf fields filled in
    by anything): those with words of their own."""
    literals = re.findall(r'"((?:[^"\\\n]|\\.)*)"', PROGRAM.read_text(encoding="utf-8"))
    out = []
    for literal in literals:
        if len(re.findall(r"[A-Za-z]", SPEC.sub("", literal))) < 4:
            continue
        parts, last = [], 0
        for m in SPEC.finditer(literal):
            parts.append(re.escape(literal[last : m.start()]))
            parts.append("%" if m.group(0) == "%%" else ANY[m.group(1)])
            last = m.end()
        parts.append(re.escape(literal[last:]))
        out.append(re.compile("".join(parts)))
    return out


def quoted_screens() -> list[str]:
    """What the guide says the screen says: in its tables headed "The screen says", and as
    "the screen says `...`"."""
    quotes = re.findall(r"screen says `([^`]+)`", prose(TEXT), flags=re.I)
    lines = prose(TEXT).splitlines()
    for k, line in enumerate(lines[:-1]):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == "The screen says":
            for row in lines[k + 2 :]:
                if not row.startswith("|"):
                    break
                quotes += re.findall(r"`([^`]+)`", row.strip().strip("|").split("|")[0])
    return quotes


def test_the_guide_quotes_the_screens():
    assert len(quoted_screens()) >= 20


@pytest.mark.parametrize("quote", quoted_screens())
def test_each_screen_it_quotes_is_the_programs(quote):
    assert any(p.fullmatch(quote) for p in screen_texts()), quote
