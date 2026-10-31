"""Copy the files the Hugging Face Space needs into an empty folder. Nothing is pushed anywhere.

Run from the repo root:  python demo/space/build.py ..\\mixshield-space
The folder must not exist or must be empty. It then holds a complete Space repo: README.md (with the Space settings),
app.py, requirements.txt, mixshield/, demo/, bench/stats_e2.py, the 30 result CSVs the results strip reads, and the
recorded runs. No .env file and no key is ever copied.
"""

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from bench import stats_e2  # noqa: E402  (the list of result files comes from the code that reads them)


def result_files() -> list[str]:
    names = {n for files in stats_e2.SCREEN_FILES.values() for n in files}
    for suffix, _ in stats_e2.SINGLE.values():
        names.update(stats_e2.single_files(suffix).values())
    return sorted(names)


def copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def check_space_files(out: Path) -> None:
    """Stop if the Space files are not the ZeroGPU ones (a stale build once overwrote them on the Space)."""
    requirements = (out / "requirements.txt").read_text(encoding="utf-8")
    readme = (out / "README.md").read_text(encoding="utf-8")
    app = (out / "app.py").read_text(encoding="utf-8")
    problems = [text for ok, text in (
        ("torch==2.13.0" in requirements, "requirements.txt must pin torch==2.13.0"),
        ("--extra-index-url" not in requirements, "requirements.txt must not have an extra index line"),
        ('python_version: "3.12"' in readme, 'README.md must have python_version: "3.12"'),
        ("@spaces.GPU" in app, "app.py must have the @spaces.GPU placeholder")) if not ok]
    if problems:
        raise SystemExit("; ".join(problems))


def build(out: Path) -> list[Path]:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    here = Path(__file__).parent
    for name in ("README.md", "app.py", "requirements.txt"):
        copy(here / name, out / name)
    copy(REPO / "LICENSE", out / "LICENSE")
    for pattern in ("mixshield/*.py", "demo/*.py", "demo/policy.json", "results/demo/runs/*.json", "bench/__init__.py",
                    "bench/stats_e2.py"):
        for src in REPO.glob(pattern):
            copy(src, out / src.relative_to(REPO))
    for name in result_files():
        copy(REPO / "results" / "e2" / name, out / "results" / "e2" / name)
    check_space_files(out)
    return sorted(p for p in out.rglob("*") if p.is_file())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python demo/space/build.py <new folder>")
    files = build(Path(sys.argv[1]).resolve())
    print(f"{len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.2f} MB")
    print("largest:", max(files, key=lambda p: p.stat().st_size).name)
