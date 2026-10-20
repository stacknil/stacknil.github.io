# stacknil.github.io

Static engineering portfolio: HTML, CSS, local assets, and no runtime dependencies.
GitHub Pages serves `index.html` from the repository's existing publishing setup.

## Local review

Python 3.12 or newer, with no package installation:

```sh
python scripts/validate_site.py
python -m unittest discover -s tests -v
python -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/`. Review at 375, 768, and 1440 px, use Tab/Enter
to exercise the skip link and navigation, and check reduced-motion behavior.

The offline gate checks basic explicit HTML nesting, headings, required targets,
local HTML/CSS references, metadata agreement, project repository URLs, and
common private-path/credential patterns. Negative controls use temporary
copies and mocked HTTP responses. It is not a full HTML, accessibility, or
secret-scanning certification; review changed content and binary assets too.

The published tree must contain regular files and directories. The gate rejects
symbolic links (including links within the tree) and Windows junctions before
reading content, then checks the resolved final file for local references.
This avoids silently following a link outside the site or skipping linked
content during the privacy scan. It is not a sandbox for concurrent filesystem
changes or untrusted Python code.

Duplicate HTML attributes are rejected rather than choosing a browser-dependent
value. Local URL paths use forward slashes; raw and encoded backslashes fail.
CSS checks cover `url(...)` and quoted `@import` references. Privacy diagnostics
report the rule without echoing file names or matched content. The pattern scan
remains limited; Linux CI also checks the actual paths on a case-sensitive host.

```sh
python scripts/validate_site.py --check-external
```

Optional HTTP checks return `0` for observed success, `1` for an offline error
or confirmed HTTP 404/410, and `2` for inconclusive network/TLS, rate-limit,
authorization, or server responses. They do not validate remote fragments or
claim that all future requests will succeed. Required CI stays offline.

## Updating content

- Keep released tag links separate from main-branch work and research cases.
- Verify project claims in the linked implementation, fixtures, and tests.
- Label reported experiments as reported; preserve their evidence limitations.
- Recheck the Profile README alongside site updates; avoid duplicating project docs.
- Keep all navigation targets, including the existing `#patterns` fragment.

`assets/social-preview.svg` is the editable source for the intentional 1200×630
PNG social card. Render that SVG in a browser at its natural size and capture
the viewport to `assets/social-preview.png` after changing it. Browser/font
versions can affect pixels; the PNG is a presentation asset, not a benchmark.
