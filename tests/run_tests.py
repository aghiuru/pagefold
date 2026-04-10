#!/usr/bin/env python3
"""Regression tests for the scraper.

Usage:
    poetry run python tests/run_tests.py            # run and compare against baseline
    poetry run python tests/run_tests.py --update   # run and save results as new baseline
"""

import sys
import shutil
import difflib
import subprocess
from pathlib import Path

TESTS_DIR = Path(__file__).parent
URLS_FILE = TESTS_DIR / "test_urls.txt"
OUTPUT_DIR = TESTS_DIR / "output"
BASELINE_DIR = TESTS_DIR / "baseline"


def scrape(url: str, out_dir: Path) -> Path | None:
    result = subprocess.run(
        ["poetry", "run", "pagefold", url, str(out_dir)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  [error] scraper exited with code {result.returncode}")
        print(result.stderr)
        return None
    # Find the markdown file that was written
    md_files = list(out_dir.rglob("*.md"))
    return max(md_files, key=lambda p: p.stat().st_mtime) if md_files else None


def strip_volatile(text: str) -> str:
    """Remove lines that change every run (timestamps, byte counts)."""
    lines = []
    for line in text.splitlines():
        if line.startswith("**Published:**"):
            continue
        lines.append(line)
    return "\n".join(lines)


def main() -> None:
    update_mode = "--update" in sys.argv
    urls = [u.strip() for u in URLS_FILE.read_text().splitlines() if u.strip()]

    OUTPUT_DIR.mkdir(exist_ok=True)
    if update_mode:
        BASELINE_DIR.mkdir(exist_ok=True)

    failures = []

    for url in urls:
        slug = url.split("//", 1)[-1].replace("/", "_").replace("?", "_")[:60]
        print(f"\n{'='*60}")
        print(f"URL: {url}")

        md_path = scrape(url, OUTPUT_DIR)
        if md_path is None:
            print(f"  [FAIL] scraper returned no output")
            failures.append((url, "scraper returned no output"))
            continue

        article_dir = md_path.parent
        images_dir = article_dir / "images"
        current_text = strip_volatile(md_path.read_text())
        current_images = sorted(p.name for p in images_dir.iterdir()) if images_dir.exists() else []

        baseline_article_dir = BASELINE_DIR / slug
        baseline_md = baseline_article_dir / md_path.name
        baseline_images_dir = baseline_article_dir / "images"

        if update_mode:
            if baseline_article_dir.exists():
                shutil.rmtree(baseline_article_dir)
            baseline_article_dir.mkdir(parents=True)
            baseline_md.write_text(current_text)
            if images_dir.exists():
                shutil.copytree(images_dir, baseline_images_dir)
            print(f"  [SAVED] baseline -> {baseline_article_dir.name}/ ({len(current_images)} image(s))")
        elif baseline_article_dir.exists():
            text_ok = True
            images_ok = True

            baseline_text = strip_volatile(baseline_md.read_text()) if baseline_md.exists() else ""
            if current_text != baseline_text:
                diff = "\n".join(difflib.unified_diff(
                    baseline_text.splitlines(), current_text.splitlines(),
                    fromfile="baseline", tofile="current", lineterm=""
                ))
                print(f"  [FAIL] markdown differs from baseline:\n{diff[:2000]}")
                failures.append((url, "markdown differs from baseline"))
                text_ok = False

            baseline_images = sorted(p.name for p in baseline_images_dir.iterdir()) if baseline_images_dir.exists() else []
            if current_images != baseline_images:
                print(f"  [FAIL] images differ — baseline: {baseline_images}, current: {current_images}")
                failures.append((url, "images differ from baseline"))
                images_ok = False

            if text_ok and images_ok:
                print(f"  [PASS] ({len(current_images)} image(s))")
        else:
            print(f"  [SKIP] no baseline yet — run with --update to create one")

    print(f"\n{'='*60}")
    if update_mode:
        print(f"Baseline updated for {len(urls)} URL(s).")
    elif failures:
        print(f"{len(failures)} test(s) FAILED:")
        for url, reason in failures:
            print(f"  - {url}: {reason}")
        sys.exit(1)
    else:
        print(f"All tests passed.")


if __name__ == "__main__":
    main()
