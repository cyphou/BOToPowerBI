"""BIAR/LCMBIAR archive reader.

Reads SAP BusinessObjects BIAR and LCMBIAR archives, extracts individual
artifacts (WebI, Crystal, Universe), and routes them for extraction.
"""

import json
import logging
import os
import xml.etree.ElementTree as ET
import zipfile

logger = logging.getLogger(__name__)


def read_biar_archive(biar_path):
    """Read a BIAR or LCMBIAR archive and list contained artifacts.

    Args:
        biar_path: Path to .biar or .lcmbiar file.

    Returns:
        list[dict]: List of artifact descriptors with name, type, and content.
    """
    biar_path = os.path.abspath(biar_path)
    if not os.path.isfile(biar_path):
        raise FileNotFoundError(f"BIAR file not found: {biar_path}")

    if not zipfile.is_zipfile(biar_path):
        raise ValueError(f"Not a valid BIAR archive: {biar_path}")

    artifacts = []

    with zipfile.ZipFile(biar_path, "r") as zf:
        # Read manifest/metadata
        manifest = _read_manifest(zf)

        for entry in zf.namelist():
            # Security: reject path traversal
            if ".." in entry or entry.startswith("/") or "\x00" in entry:
                logger.warning("Skipping suspicious BIAR entry: %s", entry)
                continue

            # Classify artifact type
            artifact_type = _classify_artifact(entry)
            if artifact_type is None:
                continue

            artifact_name = os.path.splitext(os.path.basename(entry))[0]

            artifacts.append({
                "name": artifact_name,
                "type": artifact_type,
                "path": entry,
                "biar_path": biar_path,
                "manifest_info": manifest.get(entry, {}),
            })

    logger.info("BIAR archive: %d artifacts found in %s", len(artifacts), biar_path)
    return artifacts


def extract_artifact_from_biar(biar_path, artifact_entry, output_dir):
    """Extract a single artifact from BIAR to a temporary file.

    Args:
        biar_path: Path to the BIAR archive.
        artifact_entry: ZIP entry name of the artifact.
        output_dir: Directory to extract to.

    Returns:
        str: Path to the extracted file.
    """
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(biar_path, "r") as zf:
        # Validate entry name
        entry_name = os.path.basename(artifact_entry)
        if not entry_name:
            raise ValueError(f"Invalid artifact entry: {artifact_entry}")

        output_path = os.path.join(output_dir, entry_name)

        # Security: ensure output stays within output_dir
        real_output = os.path.realpath(output_path)
        real_dir = os.path.realpath(output_dir)
        if not real_output.startswith(real_dir):
            raise ValueError(f"Path traversal detected: {artifact_entry}")

        with zf.open(artifact_entry) as src, open(output_path, "wb") as dst:
            dst.write(src.read())

    return output_path


def _read_manifest(zf):
    """Read BIAR manifest/metadata file if present."""
    manifest = {}

    manifest_names = ["manifest.xml", "metadata.xml", "content.xml", "META-INF/manifest.xml"]
    for name in manifest_names:
        if name in zf.namelist():
            try:
                content = zf.read(name).decode("utf-8", errors="replace")
                root = _safe_parse_xml(content)
                if root is not None:
                    for item in root.iter():
                        path = item.get("path", item.get("name", ""))
                        if path:
                            manifest[path] = {
                                "type": item.get("type", ""),
                                "folder": item.get("folder", ""),
                                "cuid": item.get("cuid", ""),
                                "description": item.get("description", ""),
                            }
            except Exception as e:
                logger.warning("Failed to read manifest %s: %s", name, e)

    return manifest


def _classify_artifact(entry_name):
    """Classify a BIAR entry as a BO artifact type.

    Returns:
        str or None: Artifact type ('webi', 'crystal', 'universe', 'lumira') or None.
    """
    lower = entry_name.lower()

    if lower.endswith(".wid"):
        return "webi"
    elif lower.endswith(".rpt"):
        return "crystal"
    elif lower.endswith((".unx", ".unv")):
        return "universe"
    elif lower.endswith((".lumx", ".lums")):
        return "lumira"
    elif lower.endswith((".xml", ".json")):
        # Metadata files — not standalone artifacts
        return None
    else:
        return None


def _safe_parse_xml(content):
    """Parse XML with XXE protection."""
    if not content or not content.strip():
        return None
    if "<!ENTITY" in content.upper():
        logger.warning("Blocked XML with ENTITY declaration (XXE protection)")
        return None
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        return None
