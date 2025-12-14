"""Execute the main notebook and export an input-free HTML report."""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path

import nbformat
from nbconvert import HTMLExporter
from nbconvert.preprocessors import ExecutePreprocessor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skillra_pda import config  # noqa: E402

NOTEBOOK = config.NOTEBOOKS_DIR / "01_hse_project.ipynb"
DEFAULT_TIMEOUT = int(os.environ.get("NBEXEC_TIMEOUT", "900"))
OUTPUT_HTML = config.NOTEBOOK_REPORTS_DIR / "01_hse_project.html"

CUSTOM_CSS = """
:root {
    color-scheme: light;
    --content-width: 1140px;
    --content-padding: 34px;
    --bg: #f7f8fb;
    --card-bg: #ffffff;
    --text: #0f172a;
    --muted: #475569;
    --accent: #1d4ed8;
    --border: #e2e8f0;
}

body {
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    line-height: 1.7;
    letter-spacing: -0.01em;
}

.jp-Notebook {
    max-width: var(--content-width);
    margin: 32px auto 56px auto;
    padding: var(--content-padding) calc(var(--content-padding) * 1.35);
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: 0 12px 34px rgba(15, 23, 42, 0.08);
}

h1, h2, h3, h4 {
    font-weight: 700;
    color: var(--text);
    line-height: 1.25;
}

h1 {
    font-size: 2.15rem;
    margin-top: 12px;
    margin-bottom: 12px;
    letter-spacing: -0.02em;
}

h2 {
    font-size: 1.58rem;
    margin-top: 30px;
    margin-bottom: 14px;
}

h3 {
    font-size: 1.22rem;
    margin-top: 24px;
    margin-bottom: 10px;
}

p, li {
    font-size: 1rem;
    margin: 0 0 13px 0;
    color: var(--muted);
}

ul, ol {
    padding-left: 22px;
}

a {
    color: var(--accent);
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

nav#toc-container {
    max-width: var(--content-width);
    margin: 32px auto 18px auto;
    background: linear-gradient(180deg, #f8fbff 0%, #f4f6fb 100%);
    border: 1px solid #e1e5f2;
    border-radius: 12px;
    padding: 18px 20px;
    box-shadow: 0 6px 18px rgba(15, 23, 42, 0.05);
}

#toc-container .toc-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
}

#toc-container h2 {
    margin: 0;
    font-size: 1.2rem;
}

#toc-container .toc-note {
    font-size: 0.95rem;
    color: #475569;
}

#toc-container ul {
    list-style: none;
    padding-left: 0;
    margin: 10px 0 0 0;
}

#toc-container li {
    margin: 6px 0;
    color: #334155;
}

#toc-container li ul {
    margin-left: 14px;
    border-left: 2px solid #e2e8f0;
    padding-left: 12px;
}

#toc-container a {
    color: var(--text);
}

#toc-container a:hover {
    color: var(--accent);
}

.toc-level-1 > a {
    font-weight: 600;
}

.toc-level-2 > a {
    color: #475569;
    font-size: 0.97rem;
}

.jp-Cell:not(.jp-MarkdownCell) {
    border: none;
}

.jp-OutputArea {
    padding: 6px 0 22px 0;
}

.jp-OutputArea img,
.jp-OutputArea canvas,
.jp-OutputArea svg {
    display: block;
    max-width: min(1024px, 100%);
    height: auto;
    margin: 12px auto;
    border-radius: 12px;
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
}

.jp-RenderedHTMLCommon table {
    border-collapse: collapse;
    width: 100%;
    margin: 14px 0 22px 0;
    font-size: 0.96rem;
}

.jp-RenderedHTMLCommon th,
.jp-RenderedHTMLCommon td {
    border: 1px solid var(--border);
    padding: 10px 12px;
}

.jp-RenderedHTMLCommon th {
    background: #f8fafc;
    text-align: left;
    font-weight: 700;
}

.jp-RenderedHTMLCommon td {
    color: var(--muted);
}

blockquote {
    margin: 16px 0;
    padding: 12px 16px;
    background: #f1f5f9;
    border-left: 4px solid var(--accent);
    color: #334155;
}

.heading-anchor {
    opacity: 0;
    margin-left: 8px;
    font-size: 0.9rem;
    color: var(--accent);
    text-decoration: none;
}

h1:hover .heading-anchor,
h2:hover .heading-anchor {
    opacity: 1;
}

h1, h2 {
    scroll-margin-top: 90px;
}

@media (max-width: 900px) {
    .jp-Notebook {
        padding: 22px 18px;
        margin: 12px;
    }

    nav#toc-container {
        margin: 16px 12px;
        padding: 14px 16px;
    }
}
"""

TOC_SNIPPET = """
<nav id=\"toc-container\" aria-label=\"Оглавление\">
  <div class=\"toc-header\">
    <h2>Оглавление</h2>
    <span class=\"toc-note\">Быстрый переход по разделам</span>
  </div>
  <ul id=\"toc-list\"></ul>
</nav>
<script>
document.addEventListener('DOMContentLoaded', () => {
  const tocList = document.getElementById('toc-list');
  if (!tocList) return;

  const headings = Array.from(document.querySelectorAll('h1, h2'));
  const slugCounts = {};

  const slugify = (text) => {
    const base = text.toLowerCase().replace(/[^a-z0-9\u0400-\u04ff]+/g, '-').replace(/(^-|-$)/g, '');
    const count = slugCounts[base] ?? 0;
    slugCounts[base] = count + 1;
    return count ? `${base}-${count}` : base;
  };

  let currentSection;

  headings.forEach((h) => {
    const text = h.textContent?.trim();
    if (!text) return;

    if (!h.id) {
      h.id = slugify(text);
    }

    if (!h.querySelector('.heading-anchor')) {
      const anchor = document.createElement('a');
      anchor.href = `#${h.id}`;
      anchor.className = 'heading-anchor';
      anchor.setAttribute('aria-label', `Ссылка на раздел ${text}`);
      anchor.textContent = '¶';
      h.appendChild(anchor);
    }

    if (h.tagName === 'H1') {
      const li = document.createElement('li');
      li.classList.add('toc-level-1');
      const link = document.createElement('a');
      link.textContent = text;
      link.href = `#${h.id}`;
      li.appendChild(link);

      const nested = document.createElement('ul');
      nested.classList.add('toc-sublist');
      li.appendChild(nested);
      tocList.appendChild(li);
      currentSection = nested;
      return;
    }

    if (h.tagName === 'H2') {
      const targetList = currentSection || tocList;
      const li = document.createElement('li');
      li.classList.add('toc-level-2');
      const link = document.createElement('a');
      link.textContent = text;
      link.href = `#${h.id}`;
      li.appendChild(link);
      targetList.appendChild(li);
    }
  });
});
</script>
"""


def inject_toc(html: str) -> str:
    """Insert a lightweight table of contents after the <body> tag."""

    marker = "<body>"
    if marker not in html:
        return html
    return html.replace(marker, f"{marker}\n{TOC_SNIPPET}", 1)


def embed_local_images(html: str) -> str:
    """Inline local images referenced by <img src> into data URLs.

    Nbconvert already embeds matplotlib outputs, but images referenced via
    ``<img src="reports/figures/...">`` may remain as external files.
    This helper reads such files and replaces the ``src`` attribute with a
    base64-encoded data URL to guarantee the HTML report is self-contained.
    """

    def to_data_uri(src: str) -> str:
        if src.startswith(("data:", "http://", "https://")):
            return src

        candidate_paths = [ROOT / src, NOTEBOOK.parent / src]
        for path in candidate_paths:
            if path.exists():
                mime, _ = mimetypes.guess_type(path.name)
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                return f"data:{mime or 'application/octet-stream'};base64,{encoded}"

        return src

    pattern = re.compile(r"(<img[^>]+src=)([\"'])([^\"']+)([\"'][^>]*>)", re.IGNORECASE)

    def replacer(match: re.Match[str]) -> str:
        prefix, quote, src, suffix = match.groups()
        inlined = to_data_uri(src)
        return f"{prefix}{quote}{inlined}{quote}{suffix}"

    return pattern.sub(replacer, html)


def execute_notebook() -> nbformat.NotebookNode:
    """Run the primary notebook and return the executed notebook node."""

    with NOTEBOOK.open("r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    executor = ExecutePreprocessor(timeout=DEFAULT_TIMEOUT, kernel_name="python3")
    executor.preprocess(nb, {"metadata": {"path": NOTEBOOK.parent}})
    return nb


def export_to_html(nb: nbformat.NotebookNode) -> str:
    """Render notebook to HTML with hidden inputs and inline styling."""

    exporter = HTMLExporter(template_name="lab")
    exporter.exclude_input = True
    exporter.exclude_input_prompt = True
    exporter.exclude_output_prompt = True
    exporter.embed_images = True

    resources = {
        "metadata": {"name": NOTEBOOK.stem},
        "inlining": {"css": [CUSTOM_CSS]},
        "config": {
            "InlineBackend": {
                "figure_format": "png",
                "rc": {"figure.dpi": 110},
            }
        },
    }

    body, _ = exporter.from_notebook_node(nb, resources=resources)
    body = inject_toc(body)
    return embed_local_images(body)


def main() -> None:
    """Run pipeline, execute notebook, and export an investor-ready HTML report."""

    config.ensure_directories()

    pipeline_script = Path(__file__).resolve().parent / "run_pipeline.py"
    subprocess.run([sys.executable, str(pipeline_script)], check=True)

    executed_nb = execute_notebook()
    html = export_to_html(executed_nb)
    html_path = OUTPUT_HTML.resolve()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")

    print(f"HTML-отчёт сохранён в {html_path}")


if __name__ == "__main__":
    main()
