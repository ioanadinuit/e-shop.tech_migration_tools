"""
Read a Presta ps_order_detail revenue export and emit a clean CSV with
unique product codes in the order they appear (which is the revenue
ranking, since the input is already ordered DESC by revenue).

Usage:
  python scripts/prep_top_codes.py \\
      --input "C:/path/to/ps_order_detail (1).csv" \\
      --output ./exports/biorganicbubu_top_all.csv
"""
import argparse
import csv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    seen = set()
    ordered = []

    with open(args.input, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("code") or "").strip()
            if code and code not in seen:
                seen.add(code)
                ordered.append(code)

    with open(args.output, "w", encoding="utf-8", newline="") as f:
        f.write("code\n")
        for c in ordered:
            f.write(c + "\n")

    print(f"[prep] {len(ordered)} unique codes -> {args.output}")


if __name__ == "__main__":
    main()
