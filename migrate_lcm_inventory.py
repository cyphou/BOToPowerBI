"""Read an LCM BIAR's CMS metadata and write a lineage inventory plus unbound RDL skeletons."""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from bo_export.lcm_manifest import read_lcm_manifest
from powerbi_import.paginated_generator import generate_unbound_rdl


def _file_stem(document):
    name = re.sub(r"[^\w\-. ()]+", "_", document["name"], flags=re.UNICODE).strip(" ._")[:80]
    return f"{name or 'report'}-{document['cuid'][:8]}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help=".lcmbiar archive or BusinessObjects.xml")
    parser.add_argument("--output-dir", required=True, help="New directory for the outputs")
    parser.add_argument("--no-rdl", action="store_true", help="Write only the inventory")
    args = parser.parse_args(argv)

    output = Path(args.output_dir)
    skeletons = []
    try:
        inventory = read_lcm_manifest(args.manifest)
        output.mkdir(parents=True)
        with (output / "inventory.json").open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(inventory, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        if not args.no_rdl:
            (output / "rdl").mkdir()
            for document in inventory["documents"]:
                entry = {"document": document["name"], "kind": document["kind"]}
                try:
                    rdl = generate_unbound_rdl({
                        "title": document["name"],
                        "source_kind": document["kind"],
                        "description": document["description"],
                        "parameters": [
                            {key: parameter[key]
                             for key in ("name", "prompt", "multiple", "optional")}
                            for parameter in document["parameters"]
                        ],
                    })
                    path = output / "rdl" / f"{_file_stem(document)}.rdl"
                    with path.open("x", encoding="utf-8", newline="\n") as handle:
                        handle.write(rdl + "\n")
                    entry.update(status="generated", file=f"rdl/{path.name}",
                                 parameters=len(document["parameters"]))
                except ValueError as error:
                    entry.update(status="skipped", reason=str(error))
                skeletons.append(entry)
            with (output / "skeletons.json").open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(skeletons, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
    except FileExistsError:
        print("LCM inventory failed: the output directory or a file already exists.",
              file=sys.stderr)
        return 2
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as error:
        print(f"LCM inventory failed: {error}", file=sys.stderr)
        return 2

    generated = sum(item["status"] == "generated" for item in skeletons)
    print(
        f"{len(inventory['documents'])} document(s), {len(inventory['groups'])} universe "
        f"group(s) read from CMS metadata; {generated} unbound RDL skeleton(s) written. "
        "No data, SQL, layout or formulas were converted; Report Builder rendering is not_run."
    )
    return 0 if generated == len(skeletons) else 1


if __name__ == "__main__":
    raise SystemExit(main())
