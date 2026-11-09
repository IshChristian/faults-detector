"""Fail if any installed distribution in this interpreter has a license outside the allowlist.

Run it with the interpreter of a production-only environment, e.g.
    uv sync --frozen --no-dev && .venv/bin/python scripts/check_python_licenses.py

License data is read from, in order: License-Expression (PEP 639), Trove classifiers, License.
Anything unrecognised fails the check, so a new dependency is always looked at by a human.
"""
import re
import sys
from importlib.metadata import distributions

ALLOWED = {"MIT", "MIT-0", "BSD", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Apache-2.0", "ISC",
           "PSF-2.0", "Python-2.0", "MPL-2.0", "Unlicense", "HPND", "MIT-CMU"}
FORBIDDEN_NAMES = re.compile(r"ultralytics", re.I)

CLASSIFIERS = {
    "MIT License": "MIT", "BSD License": "BSD", "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "The Unlicense (Unlicense)": "Unlicense",
    "Historical Permission Notice and Disclaimer (HPND)": "HPND",
}
# Free-text License: fields seen in the wild, mapped to SPDX ids.
TEXT = {"mit": "MIT", "mit license": "MIT", "bsd": "BSD", "bsd license": "BSD", "bsd-3-clause": "BSD-3-Clause",
        "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0",
        "apache software license": "Apache-2.0", "isc": "ISC", "psf": "PSF-2.0", "hpnd": "HPND", "mit-cmu": "MIT-CMU",
        "3-clause bsd license": "BSD-3-Clause"}


def spdx_ok(expression: str) -> bool:
    """True if an SPDX expression is satisfiable with allowed licenses (OR: any branch; AND: all)."""
    expr = expression.replace("(", " ").replace(")", " ")
    return any(all(t.strip() in ALLOWED for t in re.split(r"\s+AND\s+", branch))
               for branch in re.split(r"\s+OR\s+", expr))


def license_of(dist) -> tuple[str, bool]:
    meta = dist.metadata
    if expr := meta.get("License-Expression"):
        return expr, spdx_ok(expr)
    found = [CLASSIFIERS.get(c.split(" :: ")[-1]) for c in meta.get_all("Classifier") or []
             if c.startswith("License :: ")]
    if found:
        # Several classifiers mean the user may choose (e.g. "Apache; BSD").
        names = [f for f in found if f]
        return "; ".join(names) or "unrecognised classifier", bool(names) and any(n in ALLOWED for n in names)
    text = (meta.get("License") or "").strip()
    spdx = TEXT.get(text.lower())
    if spdx:
        return text, spdx in ALLOWED
    # Some packages put an SPDX expression (e.g. "MPL-2.0 AND MIT") in the free-text field.
    return text or "UNKNOWN", bool(text) and spdx_ok(text)


def main() -> int:
    bad = []
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        lic, ok = license_of(dist)
        if FORBIDDEN_NAMES.search(name):
            ok, lic = False, f"{lic} (forbidden package)"
        print(f"{'ok ' if ok else 'BAD'}  {name}=={dist.version}  [{lic}]")
        if not ok:
            bad.append(name)
    if bad:
        print(f"\nLicense check failed for: {', '.join(bad)}", file=sys.stderr)
        return 1
    print("\nAll licenses allowed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
