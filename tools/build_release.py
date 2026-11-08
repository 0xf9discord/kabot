"""Build and validate this version's two PyPI artifacts. Never uploads anything."""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def check_paths(names, *, wheel):
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"Unsafe archive path: {name}")
        source_gitignore = not wheel and len(path.parts) == 2 and path.name == ".gitignore"
        if not source_gitignore and any(
            part.startswith(".") or part == "__pycache__" for part in path.parts
        ):
            raise ValueError(f"Unexpected hidden/cache entry: {name}")
        if wheel:
            if path.parts[0] != "kabot" and not path.parts[0].endswith(".dist-info"):
                raise ValueError(f"Unexpected wheel entry: {name}")
        else:
            relative = PurePosixPath(*path.parts[1:])
            if relative.parts[0] not in {
                "src",
                "tests",
                "examples",
                "docs",
                "tools",
                "LICENSE",
                "README.md",
                "PYPI_README.md",
                "pyproject.toml",
                "PKG-INFO",
                ".gitignore",
            }:
                raise ValueError(f"Unexpected source entry: {name}")
            if "references" in relative.parts or "analysis" in relative.parts:
                raise ValueError(f"Research artifact in release: {name}")
        if path.suffix.lower() in {
            ".kabot",
            ".db",
            ".sqlite3",
            ".exe",
            ".dll",
            ".i64",
            ".idb",
            ".pyc",
            ".log",
            ".bin",
            ".dmp",
        }:
            raise ValueError(f"Private or generated artifact in release: {name}")


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name, version = project["name"], project["version"]
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", version):
        raise ValueError("Unsafe version")
    source = ast.parse((ROOT / "src/kabot/__init__.py").read_text(encoding="utf-8"))
    versions = [
        ast.literal_eval(node.value)
        for node in source.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    ]
    if versions != [version]:
        raise ValueError("Package and project versions differ")
    output = ROOT / "dist" / "pypi" / version
    run("-m", "build", "--outdir", str(output))
    stem = name.replace("-", "_") + "-" + version
    wheel = output / f"{stem}-py3-none-any.whl"
    sdist = output / f"{stem}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupted wheel")
        check_paths(archive.namelist(), wheel=True)
        metadata = BytesParser().parsebytes(archive.read(f"{stem}.dist-info/METADATA"))
        if metadata["Name"] != name or metadata["Version"] != version:
            raise ValueError("Incorrect wheel metadata")
        required = {"kabot/loco/open_profile.py", "kabot/THIRD_PARTY_NOTICES.md"}
        if not required.issubset(archive.namelist()):
            raise ValueError("Wheel is missing runtime code or notices")
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        if any(not member.isfile() and not member.isdir() for member in members):
            raise ValueError("Source archive contains links or special files")
        check_paths([m.name for m in members if m.isfile()], wheel=False)
    run("-m", "twine", "check", "--strict", str(wheel), str(sdist))
    hashes = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in (wheel, sdist)
    )
    (output / "SHA256SUMS.txt").write_text(hashes, encoding="utf-8")
    print(f"Validated release: {output}")
    print("No files have been uploaded.")


if __name__ == "__main__":
    main()
