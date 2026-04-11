# pagefold

Download web articles into self-contained markdown folders for offline reading and archiving.

## What it does

Given a URL, pagefold fetches the article, extracts the content as markdown, and downloads all images — producing a portable folder you can read anywhere.

```
output/
  my-article-slug/
    my-article-slug.md
    images/
      a1b2c3.jpg
      d4e5f6.png
```

The markdown file includes the title, author, publication date, source URL, and article body with local image references.

## Features

- Extracts clean markdown from articles using trafilatura
- Downloads and embeds all images (parallel, deduplicated by URL hash)
- Auto-detects JS-heavy pages and renders them with a headless browser (Playwright)
- Handles cookie consent dialogs automatically

## Installation

Requires Python 3.11+ and [pipx](https://pipx.pypa.io/).

```bash
pipx install git+https://github.com/aghiuru/pagefold.git
```

## Usage

```bash
pagefold <URL>
pagefold <URL> --output-dir ~/articles
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir DIR` | `./output` | Directory to save the article folder |
| `-h, --help` | | Show help |

## Example

```bash
pagefold "https://example.com/some-article" --output-dir ~/reading
```
