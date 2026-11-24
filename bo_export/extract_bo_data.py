"""Main orchestrator for Business Objects artifact extraction.

Routes .wid, .rpt, .unx, .unv, .biar, .lumx files to the appropriate
extractor and produces 15 intermediate JSON files for the generation pipeline.
"""

import json
import logging
import os
import re
import tempfile

from powerbi_import.security_validator import redact_connection_string

logger = logging.getLogger(__name__)

_REDACTED = "***REDACTED***"
_CREDENTIAL_FIELDS = frozenset({
    "password", "passwd", "pwd", "user", "userid", "username", "uid",
    "token", "accesstoken", "secret", "clientsecret", "credential",
    "credentials", "apikey", "accesskey", "accountkey",
    "sharedaccesssignature", "privatekey", "authorization",
})

# Supported file extensions and their extractors
SUPPORTED_EXTENSIONS = {
    ".wid": "webi",
    ".rpt": "crystal",
    ".unx": "universe",
    ".unv": "universe",
    ".biar": "biar",
    ".lcmbiar": "biar",
    ".lumx": "lumira",
    ".lums": "lumira",
}

# 15 extracted object types
EXTRACTED_TYPES = [
    "reports", "queries", "datasources", "formulas", "prompts",
    "filters", "tables", "columns", "joins", "groups",
    "sorts", "alerts", "subreports", "charts", "custom_sql",
]


def extract_bo_data(input_path, output_dir=None, verbose=False):
    """Extract data from a Business Objects artifact.

    Args:
        input_path: Path to one .wid, .rpt, .unx, .unv, .lumx, or .lums file.
            Use ``extract_from_biar`` for BIAR/LCMBIAR archives.
        output_dir: Directory for JSON output. Defaults to input filename directory.
        verbose: Enable debug logging.

    Returns:
        dict: Extracted data with keys matching EXTRACTED_TYPES.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    input_path = os.path.abspath(input_path)
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    ext = os.path.splitext(input_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS.keys())}"
        )
    extractor_type = SUPPORTED_EXTENSIONS[ext]
    if extractor_type == "biar":
        raise ValueError("Use extract_from_biar() to extract BIAR/LCMBIAR archives")

    # Determine output directory
    if output_dir is None:
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_dir = os.path.join(os.path.dirname(input_path), base_name + "_pbi")
    os.makedirs(output_dir, exist_ok=True)

    # Route to appropriate extractor
    extracted_data = _route_extraction(extractor_type, input_path, verbose)

    # Write JSON files
    _write_json_outputs(extracted_data, output_dir)

    logger.info("Extraction complete: %d object types → %s", len(extracted_data), output_dir)
    return extracted_data


def extract_from_biar(biar_path, output_dir, verbose=False):
    """Extract all artifacts from a BIAR/LCMBIAR archive.

    Args:
        biar_path: Path to .biar or .lcmbiar file.
        output_dir: Base output directory.
        verbose: Enable debug logging.

    Returns:
        list[dict]: List of extracted data dicts, one per artifact.
    """
    from bo_export.biar_reader import extract_artifact_from_biar, read_biar_archive

    artifacts = read_biar_archive(biar_path)
    names = set()
    for artifact in artifacts:
        artifact_name = artifact.get("name", "unknown")
        key = artifact_name.casefold()
        if key in names:
            raise ValueError(
                f"BIAR contains artifacts with the same output name: {artifact_name}"
            )
        names.add(key)

    results = []

    for artifact in artifacts:
        artifact_name = artifact.get("name", "unknown")
        artifact_output = os.path.join(output_dir, artifact_name + "_pbi")
        os.makedirs(artifact_output, exist_ok=True)

        ext_type = artifact.get("type", "webi")
        with tempfile.TemporaryDirectory(prefix="bo_biar_") as temporary_dir:
            source = extract_artifact_from_biar(
                biar_path, artifact["path"], temporary_dir,
            )
            extracted = _route_extraction(ext_type, source, verbose)
        _write_json_outputs(extracted, artifact_output)
        results.append(extracted)

    return results


def _route_extraction(extractor_type, input_path, verbose, artifact_data=None):
    """Route to the appropriate extractor based on file type."""
    extracted = {t: [] for t in EXTRACTED_TYPES}

    if extractor_type == "webi":
        from bo_export.webi_extractor import extract_webi
        extracted = extract_webi(input_path, artifact_data=artifact_data)

    elif extractor_type == "crystal":
        from bo_export.crystal_extractor import extract_crystal
        extracted = extract_crystal(input_path, artifact_data=artifact_data)

    elif extractor_type == "universe":
        from bo_export.universe_extractor import extract_universe
        extracted = extract_universe(input_path, artifact_data=artifact_data)

    elif extractor_type == "biar":
        raise ValueError("Use extract_from_biar() to extract BIAR/LCMBIAR archives")

    elif extractor_type == "lumira":
        from bo_export.lumira_extractor import extract_lumira
        extracted = extract_lumira(input_path, artifact_data=artifact_data)

    else:
        logger.warning("Unknown extractor type: %s", extractor_type)

    return _sanitize_extracted_datasources(extracted)


def _write_json_outputs(extracted_data, output_dir):
    """Write extracted data to individual JSON files."""
    extracted_data = _sanitize_extracted_datasources(extracted_data)
    for obj_type in EXTRACTED_TYPES:
        data = extracted_data.get(obj_type, [])
        output_path = os.path.join(output_dir, f"{obj_type}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        logger.debug("Wrote %d items to %s", len(data) if isinstance(data, list) else 1, output_path)


def load_extracted_data(project_dir):
    """Load previously extracted JSON files from a project directory.

    Args:
        project_dir: Directory containing the 15 JSON files.

    Returns:
        dict: Extracted data with keys matching EXTRACTED_TYPES.
    """
    extracted = {}
    for obj_type in EXTRACTED_TYPES:
        json_path = os.path.join(project_dir, f"{obj_type}.json")
        if os.path.isfile(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                extracted[obj_type] = json.load(f)
        else:
            extracted[obj_type] = []
    return _sanitize_extracted_datasources(extracted)


def _sanitize_extracted_datasources(extracted_data):
    """Redact recognized datasource credentials before reuse or persistence."""
    if not isinstance(extracted_data, dict):
        return extracted_data
    datasources = extracted_data.get("datasources")
    if not isinstance(datasources, list):
        return extracted_data

    sanitized = dict(extracted_data)
    sanitized["datasources"] = _sanitize_datasource_value(datasources)
    return sanitized


def _sanitize_datasource_value(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized_key in _CREDENTIAL_FIELDS:
                sanitized[key] = _REDACTED if item not in (None, "") else item
            elif normalized_key == "connectionstring" and isinstance(item, str):
                sanitized[key] = redact_connection_string(item)
            else:
                sanitized[key] = _sanitize_datasource_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_datasource_value(item) for item in value]
    return value
