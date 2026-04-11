#!/usr/bin/env python3
"""Download an article and its images as a folder with a markdown file."""

import sys
import re
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, BrowserContext

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

MIME_TO_EXT = {
    "jpeg": "jpg", "jpg": "jpg", "png": "png",
    "gif": "gif", "webp": "webp", "svg+xml": "svg",
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:80].strip("-")


def _extract_image_metadata(url: str, content_type: str) -> str:
    mime = content_type.split("/")[-1].split(";")[0].strip()
    return MIME_TO_EXT.get(mime) or Path(urlparse(url).path).suffix.lstrip(".") or "jpg"


def _save_image_file(url: str, dest: Path, ext: str, data: bytes) -> str:
    name = hashlib.md5(url.encode()).hexdigest()[:12] + "." + ext
    (dest / name).write_bytes(data)
    return name


def download_image(url: str, dest: Path, session: requests.Session) -> tuple[str, str] | tuple[str, None]:
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        ext = _extract_image_metadata(url, resp.headers.get("content-type", ""))
        return url, _save_image_file(url, dest, ext, resp.content)
    except Exception as e:
        print(f"  [warn] failed to download {url}: {e}", file=sys.stderr)
        return url, None


def download_image_via_browser(url: str, dest: Path, context: BrowserContext) -> tuple[str, str] | tuple[str, None]:
    try:
        resp = context.request.get(url)
        if not resp.ok:
            raise Exception(f"HTTP {resp.status}")
        ext = _extract_image_metadata(url, resp.headers.get("content-type", ""))
        return url, _save_image_file(url, dest, ext, resp.body())
    except Exception as e:
        print(f"  [warn] failed to download {url}: {e}", file=sys.stderr)
        return url, None


def inline_figures(html: str, base_url: str) -> str:
    """Replace <figure> tags with bare <img> so trafilatura doesn't drop them."""
    soup = BeautifulSoup(html, "lxml")
    for figure in soup.find_all("figure"):
        img = figure.find("img")
        if not img:
            continue
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
        )
        if not src or src.startswith("data:"):
            continue
        alt = img.get("alt", "")
        new_img = soup.new_tag("img", src=urljoin(base_url, src), alt=alt)
        figure.replace_with(new_img)
    return str(soup)


def fetch_html(url: str) -> tuple[str, BrowserContext | None]:
    html = trafilatura.fetch_url(url)
    if html and trafilatura.extract(html):
        return html, None

    print("  [info] JS-rendered page detected, using headless browser...")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(user_agent=USER_AGENT)
    page = context.new_page()
    page.goto(url, wait_until="networkidle", timeout=30000)
    for selector in ["button:has-text('Accept')", "button:has-text('Accept all')", "button:has-text('I agree')"]:
        btn = page.query_selector(selector)
        if btn:
            btn.click()
            page.wait_for_load_state("networkidle", timeout=10000)
            break
    try:
        page.wait_for_selector("article, .post-content, .body, main", timeout=10000)
    except Exception:
        pass
    html = page.content()
    # Return the context so its cookies/TLS fingerprint can be reused for image downloads
    return html, context


def download_images(text: str, base_url: str, images_dir: Path, browser_context: BrowserContext | None = None) -> tuple[str, int]:
    """Download images referenced in markdown, return text with local paths."""
    img_urls = [urljoin(base_url, u) for u in dict.fromkeys(re.findall(r'!\[.*?\]\((.*?)\)', text))]

    print(f"Downloading {len(img_urls)} image(s)...")
    image_map: dict[str, str] = {}

    if browser_context:
        for url in img_urls:
            orig_url, name = download_image_via_browser(url, images_dir, browser_context)
            if name:
                image_map[orig_url] = f"images/{name}"
    else:
        parsed = urlparse(base_url)
        with requests.Session() as session:
            session.headers["User-Agent"] = USER_AGENT
            session.headers["Referer"] = base_url
            session.headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(download_image, u, images_dir, session): u for u in img_urls}
                for future in as_completed(futures):
                    orig_url, name = future.result()
                    if name:
                        image_map[orig_url] = f"images/{name}"

    def replace(m: re.Match) -> str:
        return f"![{m.group(1)}]({image_map.get(urljoin(base_url, m.group(2)), m.group(2))})"

    return re.sub(r'!\[(.*?)\]\((.*?)\)', replace, text), len(image_map)


def scrape(url: str, output_dir: Path) -> None:
    print(f"Fetching: {url}")
    html, browser_context = fetch_html(url)
    html = inline_figures(html, url)

    meta = trafilatura.extract_metadata(html, default_url=url)
    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_formatting=True,
        include_comments=False,
        include_links=False,
        include_images=True,
    ) or ""
    if text.startswith("# "):
        text = text.split("\n", 1)[1].lstrip("\n")

    title = (meta.title if meta else None) or urlparse(url).netloc
    authors = meta.author if meta else None
    date = meta.date if meta else None

    folder = output_dir / (slugify(title) or "article")
    images_dir = folder / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    try:
        text, n_images = download_images(text, url, images_dir, browser_context)
    finally:
        if browser_context:
            browser_context.browser.close()

    saved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    fm = {"title": title, "source": url, "saved": saved}
    if authors:
        fm["authors"] = authors
    if date:
        fm["published"] = date

    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", f"# {title}", "", text, ""]

    md_path = folder / f"{folder.name}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved to: {folder}/")
    print(f"  {md_path.name} ({md_path.stat().st_size} bytes)")
    print(f"  {n_images} image(s) in images/")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Download an article and its images into a self-contained folder.\n"
            "\n"
            "Creates OUTPUT_DIR/<article-slug>/ containing:\n"
            "  <slug>.md   — article text in Markdown with a metadata header\n"
            "  images/     — all images referenced in the article\n"
            "\n"
            "JavaScript-heavy pages are rendered with a headless browser automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="URL of the article to scrape")
    parser.add_argument(
        "--output-dir",
        default="output",
        metavar="DIR",
        help="directory where the article folder is created (default: ./output)",
    )
    args = parser.parse_args()

    scrape(args.url, Path(args.output_dir))


if __name__ == "__main__":
    main()
