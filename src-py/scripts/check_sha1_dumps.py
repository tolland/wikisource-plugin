import argparse
import csv
import hashlib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ns = {"mw": "http://www.mediawiki.org/xml/export-0.11/"}
#
# # Read all .xml files in the specified directory
# xml_files = glob.glob('./src-py/tests/fixtures/sha_checks/*.xml')
# for file in xml_files:
#     tree = ET.parse(file)
#     root = tree.getroot()
#     revisions = root.findall(".//mw:revision", namespaces=ns)
#     print(f"{revisions=}")


MW_NAMESPACE = "http://www.mediawiki.org/xml/export-0.11/"
NS = f"{{{MW_NAMESPACE}}}"


def mediawiki_sha1(data: bytes) -> str:
    """
    Return SHA-1 in MediaWiki's zero-padded base-36 representation.
    """
    number = int.from_bytes(hashlib.sha1(data).digest(), byteorder="big")
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"

    if number == 0:
        encoded = "0"
    else:
        digits: list[str] = []

        while number:
            number, remainder = divmod(number, 36)
            digits.append(alphabet[remainder])

        encoded = "".join(reversed(digits))

    return encoded.rjust(31, "0")


def child_text(element: ET.Element, name: str) -> str | None:
    child = element.find(f"{NS}{name}")
    return child.text if child is not None else None


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def inspect_dump(path: Path):
    current_title: str | None = None
    current_namespace: str | None = None
    current_page_id: str | None = None

    # "start" is useful for detecting page boundaries; "end" lets us process
    # complete revision elements and then clear them to limit memory usage.
    context = ET.iterparse(path, events=("start", "end"))

    for event, element in context:
        if event == "start" and element.tag == f"{NS}page":
            current_title = None
            current_namespace = None
            current_page_id = None
            continue

        if event != "end":
            continue

        if element.tag == f"{NS}title":
            current_title = element.text

        elif element.tag == f"{NS}ns":
            current_namespace = element.text

        elif element.tag == f"{NS}id" and current_page_id is None:
            # The first direct page-level <id> occurs before any revisions.
            current_page_id = element.text

        elif element.tag == f"{NS}revision":
            text_element = element.find(f"{NS}text")

            if text_element is None:
                # Deleted or otherwise unavailable revision text.
                element.clear()
                continue

            text = text_element.text or ""
            content_bytes = text.encode("utf-8")

            calculated_size = len(content_bytes)
            calculated_sha1 = mediawiki_sha1(content_bytes)

            attribute_size_raw = text_element.get("bytes")
            attribute_sha1 = text_element.get("sha1")

            child_sha1 = child_text(element, "sha1")

            # Usually these two exported values are the same. Retain both so
            # any historical discrepancy is visible.
            exported_sha1 = attribute_sha1 or child_sha1

            revision_id = child_text(element, "id")
            parent_id = child_text(element, "parentid")
            timestamp = child_text(element, "timestamp")
            model = child_text(element, "model")
            content_format = child_text(element, "format")

            declared_size = (
                int(attribute_size_raw) if attribute_size_raw is not None else None
            )

            yield {
                "file": path.name,
                "page_id": current_page_id,
                "title": current_title,
                "namespace": current_namespace,
                "revision_id": revision_id,
                "parent_id": parent_id,
                "timestamp": timestamp,
                "model": model,
                "format": content_format,
                "declared_bytes": declared_size,
                "calculated_bytes": calculated_size,
                "bytes_match": (
                    declared_size == calculated_size
                    if declared_size is not None
                    else None
                ),
                "text_sha1_attribute": attribute_sha1,
                "revision_sha1_element": child_sha1,
                "exported_sha1": exported_sha1,
                "calculated_sha1": calculated_sha1,
                "sha1_match": (
                    exported_sha1 == calculated_sha1
                    if exported_sha1 is not None
                    else None
                ),
                "exported_sha_fields_match": (
                    attribute_sha1 == child_sha1
                    if attribute_sha1 is not None and child_sha1 is not None
                    else None
                ),
            }

            element.clear()

        elif element.tag == f"{NS}page":
            current_title = None
            current_namespace = None
            current_page_id = None
            element.clear()


def print_summary(rows: list[dict[str, object]]) -> None:
    print(f"Revisions checked: {len(rows):,}")

    model_counts: dict[str, Counter[bool | None]] = defaultdict(Counter)

    for row in rows:
        model = str(row["model"] or "<missing>")
        model_counts[model][row["sha1_match"]] += 1

    print("\nBy content model:")

    for model, counts in sorted(model_counts.items()):
        print(
            f"  {model:24}"
            f" match={counts[True]:7,}"
            f" mismatch={counts[False]:7,}"
            f" no-sha1={counts[None]:7,}"
        )

    mismatches = [row for row in rows if row["sha1_match"] is False]

    if not mismatches:
        print("\nNo SHA-1 mismatches found.")
        return

    print(f"\nSHA-1 mismatches: {len(mismatches):,}")

    by_model = Counter(str(row["model"] or "<missing>") for row in mismatches)

    for model, count in by_model.most_common():
        print(f"  {model:24} {count:7,}")

    dated_mismatches = [
        (parse_timestamp(str(row["timestamp"])), row)
        for row in mismatches
        if row["timestamp"]
    ]
    dated_mismatches = [
        (timestamp, row) for timestamp, row in dated_mismatches if timestamp is not None
    ]

    if dated_mismatches:
        first = min(dated_mismatches, key=lambda item: item[0])
        last = max(dated_mismatches, key=lambda item: item[0])

        print("\nMismatch date range:")
        print(
            f"  first: {first[0].isoformat()} "
            f"rev={first[1]['revision_id']} "
            f"{first[1]['title']}"
        )
        print(
            f"  last:  {last[0].isoformat()} "
            f"rev={last[1]['revision_id']} "
            f"{last[1]['title']}"
        )

    print("\nLast 10 mismatches by timestamp:")

    for timestamp, row in sorted(
        dated_mismatches,
        key=lambda item: item[0],
        reverse=True,
    )[:10]:
        print(
            f"  {timestamp.isoformat()} "
            f"model={row['model']!s:18} "
            f"rev={row['revision_id']} "
            f"{row['title']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify MediaWiki export revision sizes and SHA-1 values."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing MediaWiki XML export files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sha-checks.csv"),
        help="CSV output path",
    )
    parser.add_argument(
        "--glob",
        default="*.xml",
        help="Input filename glob, default: *.xml",
    )

    args = parser.parse_args()

    paths = sorted(args.directory.glob(args.glob))

    if not paths:
        parser.error(f"No files matching {args.glob!r} found in {args.directory}")

    rows: list[dict[str, object]] = []

    for path in paths:
        print(f"Reading {path}")
        rows.extend(inspect_dump(path))

    fieldnames = [
        "file",
        "page_id",
        "title",
        "namespace",
        "revision_id",
        "parent_id",
        "timestamp",
        "model",
        "format",
        "declared_bytes",
        "calculated_bytes",
        "bytes_match",
        "text_sha1_attribute",
        "revision_sha1_element",
        "exported_sha1",
        "calculated_sha1",
        "sha1_match",
        "exported_sha_fields_match",
    ]

    with args.output.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print_summary(rows)
    print(f"\nDetailed results written to {args.output}")


if __name__ == "__main__":
    main()
