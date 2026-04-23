.PHONY: ui

ui:
	@npx @tailwindcss/cli -i imnot/ui/input.css --minify | python3 -c "\
import sys, pathlib; \
css = sys.stdin.read(); \
p = pathlib.Path('imnot/ui/index.html'); \
p.write_text(p.read_text().replace('<!-- TAILWIND_CSS_PLACEHOLDER -->', '<style>' + css + '</style>'))"
	@echo "Tailwind CSS inlined into imnot/ui/index.html"
