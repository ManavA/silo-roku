#!/usr/bin/env python3
"""Build a sideload ZIP containing only Roku runtime files."""

import argparse
from pathlib import Path
import zipfile

REQUIRED = ("manifest", "source/main.brs", "components/SiloUIScene.xml")
PACKAGE_DIRS = ("source", "components", "images")
STOCK_ENGINE_MULTI = ("RemoteIngest", "StockDescriptor", "Rolling", "RollingTelemetry",
                      "SeekPolicy", "SeekHandoff", "MultiPolicy", "StopPolicy", "AdmissionPolicy")
STOCK_ENGINE_BASE = ("FileExtract", "HttpPolicy", "ExtractAudio")


def stock_engine_sources(root: Path) -> dict[str, Path]:
    """Resolve exact engine bytes from the revision being packaged."""
    root = root.resolve()
    experiment = root / "tools/experiments/onroku_audio"
    sources = {"components/SiloStockEngineTask.brs": experiment / "multi_app/components/LocalHttpTask.brs"}
    for name in STOCK_ENGINE_MULTI:
        sources[f"source/{name}.brs"] = experiment / f"multi_app/source/{name}.brs"
    for name in STOCK_ENGINE_BASE:
        sources[f"source/{name}.brs"] = experiment / f"app/source/{name}.brs"
    for name, path in sources.items():
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root) or (root / name).exists():
            raise ValueError("stock engine source missing or collides: " + name)
    return sources


def build_archive(root: Path, archive: Path, *, scene: str = "SiloUIScene") -> None:
    root = root.resolve()
    if scene != "SiloUIScene":
        raise ValueError("unsupported Roku entry scene")
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        raise ValueError("missing Roku channel file: " + ", ".join(missing))
    if not (root / "manifest").read_bytes().endswith(b"\n"):
        raise ValueError("manifest must end with a newline")

    files = [root / "manifest"]
    for directory in PACKAGE_DIRS:
        folder = root / directory
        if folder.exists():
            files.extend(path for path in folder.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("channel files must stay within the project: " + str(path))

    extra = {}
    if (root / "components/SiloStockEngineTask.xml").is_file():
        extra = stock_engine_sources(root)

    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(files):
            name = path.relative_to(root).as_posix()
            output.write(path, name)
        for name, path in sorted(extra.items()):
            output.write(path, name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/silo-roku.zip"))
    parser.add_argument("--scene", choices=("SiloUIScene",), default="SiloUIScene")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    build_archive(root, root / args.output, scene=args.scene)
    print(root / args.output)


if __name__ == "__main__":
    main()
