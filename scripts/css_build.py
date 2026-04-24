"""
css_build.py  --  toggle index.html between dev (link tags) and prod (inlined style)

Usage:
  python3 scripts/css_build.py ui   # inline CSS for production / wheel packaging
  python3 scripts/css_build.py dev  # restore <link> tags for Live Server editing
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent
INDEX = ROOT / "imnot" / "ui" / "index.html"
CSS_DIR = ROOT / "imnot" / "ui" / "css"
CSS_FILES = ["base.css", "header.css", "main.css", "footer.css"]

START = "<!-- IMNOT:CSS:START \u2014 do not edit this line -->"
END   = "<!-- IMNOT:CSS:END \u2014 do not edit this line -->"
PATTERN = re.compile(
    r"<!-- IMNOT:CSS:START \u2014 do not edit this line -->.*?<!-- IMNOT:CSS:END \u2014 do not edit this line -->",
    re.DOTALL,
)


def _apply(block: str) -> None:
    html = INDEX.read_text()
    if START not in html or END not in html:
        print("ERROR: IMNOT:CSS sentinel markers not found in index.html \u2014 nothing changed.")
        sys.exit(1)
    new_html = PATTERN.sub(block, html, count=1)
    INDEX.write_text(new_html)


def inline_css():
    combined = "\n".join((CSS_DIR / f).read_text() for f in CSS_FILES)
    block = "\n".join([
        START,
        "  <!-- Stylesheets inlined by make ui \u2014 run 'make dev' to restore link tags -->",
        "  <style>",
        combined,
        "  </style>",
        "  " + END,
    ])
    _apply(block)
    print("CSS inlined into imnot/ui/index.html  (run 'make dev' to restore link tags)")


def restore_links():
    block = "\n".join([
        START,
        "  <!-- Stylesheets: edit css/*.css files; Live Server picks up changes instantly.",
        "       Run `make ui` to inline for production. Run `make dev` to restore this dev state. -->",
        '  <link rel="stylesheet" href="css/base.css" />',
        '  <link rel="stylesheet" href="css/header.css" />',
        '  <link rel="stylesheet" href="css/main.css" />',
        '  <link rel="stylesheet" href="css/footer.css" />',
        "  " + END,
    ])
    _apply(block)
    print("Link tags restored in imnot/ui/index.html  (Live Server is ready)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ui":
        inline_css()
    elif cmd == "dev":
        restore_links()
    else:
        print(__doc__)
        sys.exit(1)
