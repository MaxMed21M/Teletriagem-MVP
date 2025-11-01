"""Utility script to inspect runtime environment."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

import pkg_resources


def main() -> None:
    print("Python:", sys.version)
    print("Platform:", platform.platform())
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    if requirements.exists():
        print("Packages esperados:")
        for line in requirements.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            print(" -", line)
    print("Pacotes instalados:")
    for pkg in sorted(pkg_resources.working_set, key=lambda p: p.project_name.lower()):
        print(f" - {pkg.project_name}=={pkg.version}")


if __name__ == "__main__":
    main()
