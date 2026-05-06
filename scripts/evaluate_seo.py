"""
Score each product in produse-ready.csv on SEO health and emit a CSV
ready for upload via /admin/products/seo/upload.

Input: produse-ready.csv (or any CSV with columns: code, name, description,
       meta_title, meta_description, meta_keywords, slug)

Output: seo-evaluation-ready.csv with columns: code, score, feedback
        - score: integer 0-100
        - feedback: JSON array of {label, pass, hint} — admin UI renders
                    as a structured checklist with green/yellow icons

Scoring rubric (sums to 100):
  meta_title populated + 30-60 chars              15
  meta_title contains keyword from name           10
  meta_description populated + 120-160 chars      15
  meta_description contains keyword from name     10
  meta_keywords populated (3-10 entries)          10
  slug populated, hyphenated, < 75 chars          10
  description >= 300 chars                        15
  description contains <h2> or <h3>               10
  description contains keyword from name           5

Usage:
  python scripts/evaluate_seo.py \\
      --produse-csv ./ready/produse-ready.csv \\
      --out ./ready/seo-evaluation-ready.csv
"""
import argparse
import csv
import json
import os
import re
import sys

csv.field_size_limit(2**31 - 1)


# ── Tunable rubric weights ──────────────────────────────────────────────────
W_META_TITLE_PRESENT = 15
W_META_TITLE_KEYWORD = 10
W_META_DESC_PRESENT  = 15
W_META_DESC_KEYWORD  = 10
W_META_KEYWORDS      = 10
W_SLUG               = 10
W_DESC_LENGTH        = 15
W_DESC_HEADING       = 10
W_DESC_KEYWORD       = 5
# Total: 100

# Length sweet spots per Google / Yoast convention
META_TITLE_MIN, META_TITLE_MAX = 30, 60
META_DESC_MIN,  META_DESC_MAX  = 120, 160
DESC_MIN_CHARS                 = 300
SLUG_MAX_LEN                   = 75
KEYWORDS_MIN, KEYWORDS_MAX     = 3, 10

# Filter out structural or ambiguous tokens before keyword overlap
STOPWORDS_RO = {
    "si", "in", "la", "de", "cu", "pentru", "din", "ca", "ce", "sa", "se",
    "el", "ea", "pe", "fara", "g", "ml", "cl", "kg", "l", "buc", "set",
    "bio", "natural", "naturale", "organic", "organica", "organice",
}


def _tokens(text):
    """Lowercased word tokens, filtered through stopword list."""
    if not text:
        return set()
    raw = re.findall(r"[a-zA-ZÀ-ſ0-9]+", text.lower())
    return {t for t in raw if len(t) >= 3 and t not in STOPWORDS_RO}


def _has_keyword_overlap(haystack, name):
    """True if at least 1 non-trivial token from name appears in haystack."""
    name_kw = _tokens(name)
    if not name_kw:
        return False
    haystack_kw = _tokens(haystack)
    return bool(name_kw & haystack_kw)


def _check(label, pass_, hint, weight):
    """Build a check dict + return weight if pass else 0."""
    return {"label": label, "pass": pass_, "hint": hint}, (weight if pass_ else 0)


def evaluate(row):
    """Return (score:int, checks:list[dict]) — checks are JSON-serializable
    rows the admin UI renders as a structured checklist."""
    name = (row.get("name") or "").strip()
    meta_title = (row.get("meta_title") or "").strip()
    meta_desc  = (row.get("meta_description") or "").strip()
    meta_kw    = (row.get("meta_keywords") or "").strip()
    slug       = (row.get("slug") or "").strip()
    desc       = (row.get("description") or "").strip()

    score = 0
    checks = []

    # meta_title length
    if meta_title and META_TITLE_MIN <= len(meta_title) <= META_TITLE_MAX:
        c, w = _check("Meta title", True, f"Lungime {len(meta_title)} caractere — ideal.", W_META_TITLE_PRESENT)
    elif meta_title:
        c, w = _check("Meta title", False,
                      f"Lungime {len(meta_title)} caractere — recomandat {META_TITLE_MIN}-{META_TITLE_MAX} pentru a fi afisat complet in Google.",
                      W_META_TITLE_PRESENT)
    else:
        c, w = _check("Meta title", False, "Lipseste — adauga un titlu SEO de 30-60 caractere.", W_META_TITLE_PRESENT)
    checks.append(c); score += w

    # meta_title contains keywords from name
    if meta_title:
        if _has_keyword_overlap(meta_title, name):
            c, w = _check("Cuvinte cheie in meta title", True, "Meta title contine cuvinte din numele produsului.", W_META_TITLE_KEYWORD)
        else:
            c, w = _check("Cuvinte cheie in meta title", False,
                          "Meta title nu contine cuvinte cheie din numele produsului.", W_META_TITLE_KEYWORD)
        checks.append(c); score += w

    # meta_description length
    if meta_desc and META_DESC_MIN <= len(meta_desc) <= META_DESC_MAX:
        c, w = _check("Meta description", True, f"Lungime {len(meta_desc)} caractere — ideal.", W_META_DESC_PRESENT)
    elif meta_desc:
        c, w = _check("Meta description", False,
                      f"Lungime {len(meta_desc)} caractere — recomandat {META_DESC_MIN}-{META_DESC_MAX}.",
                      W_META_DESC_PRESENT)
    else:
        c, w = _check("Meta description", False, "Lipseste — adauga o descriere SEO de 120-160 caractere.", W_META_DESC_PRESENT)
    checks.append(c); score += w

    # meta_description keywords
    if meta_desc:
        if _has_keyword_overlap(meta_desc, name):
            c, w = _check("Cuvinte cheie in meta description", True,
                          "Meta description contine cuvinte din numele produsului.", W_META_DESC_KEYWORD)
        else:
            c, w = _check("Cuvinte cheie in meta description", False,
                          "Meta description nu contine cuvinte cheie din numele produsului.", W_META_DESC_KEYWORD)
        checks.append(c); score += w

    # meta_keywords
    if meta_kw:
        count = len([k for k in meta_kw.split(",") if k.strip()])
        if KEYWORDS_MIN <= count <= KEYWORDS_MAX:
            c, w = _check("Meta keywords", True, f"{count} cuvinte cheie — bine.", W_META_KEYWORDS)
        else:
            c, w = _check("Meta keywords", False,
                          f"{count} cuvinte cheie — recomandat {KEYWORDS_MIN}-{KEYWORDS_MAX}.", W_META_KEYWORDS)
    else:
        c, w = _check("Meta keywords", False, "Lipsesc — adauga 3-10 cuvinte cheie separate prin virgula.", W_META_KEYWORDS)
    checks.append(c); score += w

    # slug
    if slug and "-" in slug and len(slug) <= SLUG_MAX_LEN and slug.lower() == slug:
        c, w = _check("URL slug", True, f"Slug bine format ({len(slug)} caractere, hyphenat).", W_SLUG)
    elif slug:
        problem = []
        if len(slug) > SLUG_MAX_LEN: problem.append(f"prea lung ({len(slug)} caractere, max {SLUG_MAX_LEN})")
        if "-" not in slug: problem.append("nu este hyphenat")
        if slug.lower() != slug: problem.append("contine majuscule")
        c, w = _check("URL slug", False, "Slug malformat: " + ", ".join(problem) + ".", W_SLUG)
    else:
        c, w = _check("URL slug", False, "Lipseste — slug-ul e cheia URL-ului produsului.", W_SLUG)
    checks.append(c); score += w

    # description length
    if desc and len(desc) >= DESC_MIN_CHARS:
        c, w = _check("Descriere consistenta", True, f"Lungime {len(desc)} caractere — bine.", W_DESC_LENGTH)
    elif desc:
        c, w = _check("Descriere consistenta", False,
                      f"Doar {len(desc)} caractere — recomandat min. {DESC_MIN_CHARS}. Adauga beneficii, mod folosire, ingrediente.",
                      W_DESC_LENGTH)
    else:
        c, w = _check("Descriere consistenta", False, "Lipseste descrierea produsului.", W_DESC_LENGTH)
    checks.append(c); score += w

    # description headings
    if desc:
        if re.search(r"<h[23][\s>]", desc, re.IGNORECASE):
            c, w = _check("Structura descriere (h2/h3)", True, "Descrierea contine headinguri h2/h3.", W_DESC_HEADING)
        else:
            c, w = _check("Structura descriere (h2/h3)", False,
                          "Adauga headinguri h2/h3 in descriere pentru structura SEO (gen 'Beneficii', 'Mod de folosire').",
                          W_DESC_HEADING)
        checks.append(c); score += w

    # description keywords
    if desc:
        if _has_keyword_overlap(desc, name):
            c, w = _check("Cuvinte cheie in descriere", True, "Descrierea contine cuvinte din numele produsului.", W_DESC_KEYWORD)
        else:
            c, w = _check("Cuvinte cheie in descriere", False,
                          "Descrierea nu mentioneaza cuvintele cheie din numele produsului.", W_DESC_KEYWORD)
        checks.append(c); score += w

    return score, checks


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--produse-csv", required=True,
                   help="Input CSV (e.g. ready/produse-ready.csv)")
    p.add_argument("--out", required=True, help="Output CSV path")
    args = p.parse_args()

    if not os.path.exists(args.produse_csv):
        sys.exit(f"ERROR: input not found: {args.produse_csv}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    with open(args.produse_csv, encoding="utf-8", newline="") as fin, \
         open(args.out, "w", encoding="utf-8", newline="") as fout:
        rdr = csv.DictReader(fin)
        wtr = csv.DictWriter(fout, fieldnames=["code", "score", "feedback"],
                             quoting=csv.QUOTE_MINIMAL)
        wtr.writeheader()

        total, total_score = 0, 0
        buckets = {"0-49": 0, "50-69": 0, "70-89": 0, "90-100": 0}
        for row in rdr:
            code = (row.get("code") or "").strip()
            if not code:
                continue
            score, checks = evaluate(row)
            # Serialize checks as JSON so the admin UI's pretty-list renderer
            # picks them up (Array.isArray(parsedSeoFeedback) branch).
            wtr.writerow({"code": code, "score": score,
                          "feedback": json.dumps(checks, ensure_ascii=False)})
            total += 1
            total_score += score
            if score < 50:    buckets["0-49"]   += 1
            elif score < 70:  buckets["50-69"]  += 1
            elif score < 90:  buckets["70-89"]  += 1
            else:             buckets["90-100"] += 1

    print(f"Scored {total} products -> {args.out}")
    if total:
        print(f"Average score: {total_score / total:.1f}/100")
        print("Distribution:")
        for label, count in buckets.items():
            pct = (count / total) * 100
            print(f"  {label:>6}: {count:>5}  ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
