"""The VS Code extension (``vexsim/ui/vscode``) packaged as a .vsix, and installed in VS Code:
``vexsim vscode``.

The package has this vexsim's version, and runs vexsim with this Python: the default of
its ``vexsim.python`` setting. A .vsix is a zip of the extension (under ``extension/``),
an ``extension.vsixmanifest`` that describes it and a ``[Content_Types].xml``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from vexsim import __version__
from vexsim.bridge.build import NO_CONSOLE

EXTENSION = Path(__file__).parent / "vscode"
ICON = Path(__file__).parent / "static" / "icons" / "vexsim-192.png"
FILES = ("extension.js", "panel.js", "README.md")
ID = "vexsim.vexsim"  # publisher.name

_TYPES = """\
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json"/>
  <Default Extension=".js" ContentType="application/javascript"/>
  <Default Extension=".md" ContentType="text/markdown"/>
  <Default Extension=".png" ContentType="image/png"/>
  <Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>
"""

_MANIFEST = """\
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" \
xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{name}" Version="{version}" Publisher="{publisher}"/>
    <DisplayName>{display}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Categories>Other</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{engine}"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace"/>
    </Properties>
    <Icon>extension/media/vexsim.png</Icon>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" \
Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" \
Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/media/vexsim.png" \
Addressable="true"/>
  </Assets>
</PackageManifest>
"""


class VsixError(RuntimeError):
    """The extension couldn't be installed."""


def manifest(python: str | None = None) -> dict:
    """The extension's package.json: this version, and ``python`` (this one) to run vexsim."""
    package = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
    package["version"] = __version__
    setting = package["contributes"]["configuration"]["properties"]["vexsim.python"]
    setting["default"] = python or sys.executable
    return package


def build(out: Path, python: str | None = None) -> Path:
    """Write the extension as a .vsix at ``out``."""
    package = manifest(python)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as vsix:
        vsix.writestr("[Content_Types].xml", _TYPES)
        vsix.writestr(
            "extension.vsixmanifest",
            _MANIFEST.format(
                name=escape(package["name"]),
                version=escape(package["version"]),
                publisher=escape(package["publisher"]),
                display=escape(package["displayName"]),
                description=escape(package["description"]),
                engine=escape(package["engines"]["vscode"]),
            ),
        )
        vsix.writestr("extension/package.json", json.dumps(package, indent=2) + "\n")
        for name in FILES:
            vsix.write(EXTENSION / name, f"extension/{name}")
        vsix.write(ICON, "extension/media/vexsim.png")
    return out


def find_code(name: str = "code") -> str | None:
    """VS Code's command (or another editor's of its kind: code-insiders, cursor, codium):
    on PATH, else where VS Code is usually installed."""
    found = shutil.which(name)
    if found or name != "code":
        return found
    if sys.platform == "win32":
        roots = [("LOCALAPPDATA", "Programs"), ("ProgramFiles", "")]
        places = [
            Path(os.environ[name], below, "Microsoft VS Code", "bin", "code.cmd")
            for name, below in roots
            if os.environ.get(name)
        ]
    elif sys.platform == "darwin":
        app = "/Applications/Visual Studio Code.app"
        places = [Path(app, "Contents", "Resources", "app", "bin", "code")]
    else:
        places = [Path("/usr/share/code/bin/code"), Path("/snap/bin/code")]
    return next((str(place) for place in places if place.is_file()), None)


def install(vsix: Path, code: str) -> str:
    """Install the .vsix with the editor's command ``code`` (replacing an older one); what it
    said."""
    try:
        result = subprocess.run(
            [code, "--install-extension", str(vsix), "--force"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=NO_CONSOLE,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VsixError(f"{code} didn't run: {exc}") from exc
    said = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise VsixError(f"{code} couldn't install it: {said}")
    return said
