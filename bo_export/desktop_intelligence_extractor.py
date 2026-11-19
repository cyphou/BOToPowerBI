"""Experimental, read-only inventory of selected Desktop Intelligence streams."""

import ctypes
import hashlib
import re
import struct
import sys
import zipfile
from pathlib import Path

_DESKI_FILE_LIMIT = 256 * 1024 * 1024
_DESKI_STREAM_LIMIT = 16 * 1024 * 1024
_DESKI_TOTAL_LIMIT = 64 * 1024 * 1024
_DESKI_SCAN_LIMIT = 16 * 1024 * 1024
_DESKI_MATCH_LIMIT = 4096
_DESKI_SHEET_LIMIT = 256
_DESKI_MEMBER_LIMIT = 10000
_DESKI_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_DESKI_PROVIDER_STREAM = "GDM|/DM|/DPList;"
_DESKI_DICTIONARY_STREAM = "GDM|/DM|/DMDict;"
_DESKI_SHEETS_STREAM = "ReportSheets|/ReportSheetList;"
_DESKI_PROVIDER_PATTERN = re.compile(rb"#DP#[0-9]{1,6}")
_DESKI_SELECT_PATTERN = re.compile(rb"\bSELECT\b", re.IGNORECASE)
_DESKI_FROM_PATTERN = re.compile(r"\bFROM\b", re.IGNORECASE)
_DESKI_BO_CALL_PATTERN = re.compile(r"@(variable|prompt|dpvalues|dpend)\b", re.IGNORECASE)
_DESKI_LITERAL_CALL_PATTERN = re.compile(
    r"@(variable|prompt)\s*\(\s*'((?:[^']|'')*)'", re.IGNORECASE,
)
_DESKI_VISUAL_MARKERS = (b"BOWOBTableBlockFmt", b"BOGraphBlockFmt")


def _deski_check_size(size, remaining):
    if size < 0 or size > _DESKI_STREAM_LIMIT or size > remaining:
        raise ValueError("selected REP streams exceed the read limits")


class _DeskiZipStorage:
    def __init__(self, path):
        self._archive = zipfile.ZipFile(path)
        entries = self._archive.infolist()
        if len(entries) > _DESKI_MEMBER_LIMIT:
            self._archive.close()
            raise ValueError("REP ZIP contains too many members")
        self._entries = {}
        self._remaining = _DESKI_TOTAL_LIMIT
        for info in entries:
            self._entries.setdefault(info.filename.casefold(), []).append(info)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._archive.close()

    def read(self, name):
        entries = self._entries.get(name.casefold(), [])
        if not entries:
            return None
        if len(entries) != 1:
            raise ValueError(f"ambiguous duplicate REP stream: {name}")
        info = entries[0]
        if info.is_dir():
            raise ValueError(f"expected a REP stream, not a directory: {name}")
        if info.flag_bits & 1:
            raise ValueError(f"selected REP stream is encrypted: {name}")
        _deski_check_size(info.file_size, self._remaining)
        with self._archive.open(info) as member:
            data = member.read(_DESKI_STREAM_LIMIT + 1)
        if len(data) != info.file_size:
            raise ValueError(f"REP stream length does not match ZIP metadata: {name}")
        self._remaining -= len(data)
        return data


class _DeskiFileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _DeskiGuid(ctypes.Structure):
    _fields_ = [
        ("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16),
        ("d", ctypes.c_ubyte * 8),
    ]


class _DeskiStat(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_void_p), ("type", ctypes.c_uint32),
        ("size", ctypes.c_uint64), ("mtime", _DeskiFileTime),
        ("ctime", _DeskiFileTime), ("atime", _DeskiFileTime),
        ("mode", ctypes.c_uint32), ("locks", ctypes.c_uint32),
        ("clsid", _DeskiGuid), ("state", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


def _deski_com_call(pointer, index, result_type, argument_types, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(table[index])
    return method(pointer, *arguments)


def _deski_com_error(result, operation):
    if result < 0:
        raise OSError(f"{operation} failed (HRESULT 0x{result & 0xffffffff:08x})")


def _deski_com_release(pointer):
    if pointer:
        _deski_com_call(pointer, 2, ctypes.c_uint32, [])


class _DeskiOleStorage:
    def __init__(self, path):
        if sys.platform != "win32":
            raise ValueError("OLE REP inspection requires Windows Structured Storage")
        ole = ctypes.WinDLL("ole32")
        ole.StgOpenStorage.argtypes = [
            ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
        ]
        ole.StgOpenStorage.restype = ctypes.c_int32
        self._root = ctypes.c_void_p()
        result = ole.StgOpenStorage(str(path.resolve()), None, 0x10, None, 0,
                                    ctypes.byref(self._root))
        _deski_com_error(result, "Opening OLE storage")
        self._remaining = _DESKI_TOTAL_LIMIT

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        _deski_com_release(self._root)
        self._root = ctypes.c_void_p()

    def read(self, name):
        parts = name.split("/")
        parents = []
        stream = ctypes.c_void_p()
        current = self._root
        try:
            for part in parts[:-1]:
                child = ctypes.c_void_p()
                result = _deski_com_call(
                    current, 6, ctypes.c_int32,
                    [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
                     ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)],
                    part, None, 0x10, None, 0, ctypes.byref(child),
                )
                if result & 0xffffffff in (0x80030002, 0x80030003):
                    return None
                _deski_com_error(result, "Opening OLE substorage")
                parents.append(child)
                current = child

            result = _deski_com_call(
                current, 4, ctypes.c_int32,
                [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
                 ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)],
                parts[-1], None, 0x10, 0, ctypes.byref(stream),
            )
            if result & 0xffffffff in (0x80030002, 0x80030003):
                return None
            _deski_com_error(result, "Opening OLE stream")
            stat = _DeskiStat()
            result = _deski_com_call(
                stream, 12, ctypes.c_int32,
                [ctypes.POINTER(_DeskiStat), ctypes.c_uint32], ctypes.byref(stat), 1,
            )
            _deski_com_error(result, "Reading OLE stream metadata")
            if stat.type != 2:
                raise ValueError(f"expected an OLE stream: {name}")
            _deski_check_size(stat.size, self._remaining)
            buffer = ctypes.create_string_buffer(stat.size or 1)
            count = ctypes.c_uint32()
            result = _deski_com_call(
                stream, 3, ctypes.c_int32,
                [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
                buffer, stat.size, ctypes.byref(count),
            )
            _deski_com_error(result, "Reading OLE stream")
            if count.value != stat.size:
                raise ValueError(f"incomplete OLE stream: {name}")
            self._remaining -= count.value
            return buffer.raw[:count.value]
        finally:
            _deski_com_release(stream)
            for parent in reversed(parents):
                _deski_com_release(parent)


def _deski_hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        signature = handle.read(8)
        handle.seek(0)
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > _DESKI_FILE_LIMIT:
                raise ValueError("REP file exceeds the read limit")
            digest.update(chunk)
    return digest.hexdigest(), size, signature


def _deski_lp_text(data, position):
    if position < 0 or position + 2 > len(data):
        raise ValueError("truncated string length")
    length = int.from_bytes(data[position:position + 2], "little")
    start = position + 2
    end = start + length
    if end > len(data):
        raise ValueError("truncated string")
    text = data[start:end].decode("utf-8")
    if any(not character.isprintable() for character in text):
        raise ValueError("unsupported control character in string")
    return text, end


def _deski_u32(data, position):
    if position < 0 or position + 4 > len(data):
        raise ValueError("truncated integer")
    return struct.unpack_from("<I", data, position)[0]


def _deski_version(data, name, warnings):
    if data is None:
        warnings.append(f"Missing optional stream: {name}.")
        return None
    try:
        version = data.rstrip(b"\x00").decode("ascii")
    except UnicodeDecodeError:
        warnings.append(f"Unsupported version text in {name}.")
        return None
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", version):
        warnings.append(f"Unsupported version text in {name}.")
        return None
    return version


def _deski_sheets(data, warnings):
    sheets = []
    declared = None
    try:
        version, position = _deski_lp_text(data, 0)
        header, position = _deski_lp_text(data, position)
        if (version, header) != ("V1.1.0", "BusinessObjects 5.0 Report Sheet List"):
            raise ValueError("unsupported sheet-list header")
        position += 8
        if _deski_u32(data, position) != 0xffffffff:
            raise ValueError("unsupported sheet-list marker")
        label, position = _deski_lp_text(data, position + 4)
        if label != "BOReportSheetsList":
            raise ValueError("unsupported sheet-list class")
        declared = _deski_u32(data, position + 4)
        position += 8
        if declared > _DESKI_SHEET_LIMIT:
            raise ValueError("sheet count exceeds the read limit")
        if declared:
            if _deski_u32(data, position) != 0xffffffff:
                raise ValueError("unsupported first sheet marker")
            label, position = _deski_lp_text(data, position + 4)
            if label != "_BOReportSheet":
                raise ValueError("unsupported sheet class")
        for index in range(declared):
            if index:
                if _deski_u32(data, position) != 0x80000003:
                    raise ValueError("unsupported subsequent sheet marker")
                position += 4
            offset = position
            name, position = _deski_lp_text(data, position)
            storage, position = _deski_lp_text(data, position)
            if not name or position + 36 > len(data):
                raise ValueError("incomplete sheet record")
            position += 36
            sheets.append({
                "name": name, "storage": storage, "stream_offset": offset,
                "stream": _DESKI_SHEETS_STREAM, "structure_markers": [],
            })
    except (ValueError, UnicodeDecodeError) as error:
        warnings.append(f"Sheet-list parsing stopped: {error}.")
    return {"declared_count": declared, "candidates": sheets}


def _deski_providers(data, warnings):
    providers = []
    declared = None
    try:
        version, position = _deski_lp_text(data, 0)
        marker, position = _deski_lp_text(data, position)
        if (not re.fullmatch(r"V[0-9]+\.[0-9]+", version)
                or marker not in {"Mercury", "Tosca", "Tosca_Unicode",
                                  "Tosca_Unicode_64K"}):
            raise ValueError("unsupported provider-list header")
        declared = _deski_u32(data, position + 8)
        if declared > _DESKI_MATCH_LIMIT:
            raise ValueError("provider count exceeds the read limit")
    except (ValueError, UnicodeDecodeError) as error:
        warnings.append(f"Provider-list header not recognized: {error}.")
        return {"declared_count": None, "candidates": providers}

    decode_warning = False
    for index, match in enumerate(_DESKI_PROVIDER_PATTERN.finditer(data)):
        if index >= _DESKI_MATCH_LIMIT:
            warnings.append("Provider marker scan reached its limit.")
            break
        offset = match.start()
        if offset < 2 or int.from_bytes(data[offset - 2:offset], "little") != len(match.group()):
            continue
        try:
            provider_type, position = _deski_lp_text(data, match.end())
            if not re.fullmatch(r"DP[A-Za-z0-9]{2,12}", provider_type):
                continue
            name, _ = _deski_lp_text(data, position)
        except UnicodeDecodeError:
            decode_warning = True
            continue
        except ValueError:
            continue
        if name:
            providers.append({
                "id": match.group().decode("ascii"), "name": name,
                "provider_type_marker": provider_type, "stream": _DESKI_PROVIDER_STREAM,
                "stream_offset": offset - 2,
            })
    if decode_warning:
        warnings.append("Some provider strings are not UTF-8; they were not decoded.")
    if declared != len(providers) or len({item["id"] for item in providers}) != len(providers):
        warnings.append("Provider candidates do not uniquely match the declared provider count.")
    return {"declared_count": declared, "candidates": providers}


def _deski_query_metadata(data, stream, warnings):
    try:
        record_marker = _deski_u32(data, 0)
        if record_marker not in (5, 6) or data[4:6] != b"\x00\x00":
            raise ValueError("unsupported query record marker")
        label, position = _deski_lp_text(data, 6)
        if data[position:position + 8] != b"\x03\x00\x00\x00\x00\x00\x01\x00":
            raise ValueError("unsupported query name marker")
        name, position = _deski_lp_text(data, position + 8)
        source_name, position = _deski_lp_text(data, position)
        if not label or not name or not source_name or data[position:position + 4] != b"\x00\x00\x01\x00":
            raise ValueError("incomplete query source record")
    except (ValueError, UnicodeDecodeError) as error:
        warnings.append(f"Query metadata could not be decoded in {stream}: {error}.")
        return None
    return {
        "query_label_candidate": label, "query_name_candidate": name,
        "source_name_candidate": source_name,
        "source_interpretation": "possible_universe_not_verified",
        "record_marker": record_marker, "stream": stream,
    }


def _deski_sql(data, providers, warnings):
    candidates = []
    scan_budget = _DESKI_SCAN_LIMIT
    accepted_until = 0
    provider_items = providers["candidates"]
    can_associate = (
        providers["declared_count"] == len(provider_items)
        and len({item["id"] for item in provider_items}) == len(provider_items)
    )
    undecodable = False
    for index, match in enumerate(_DESKI_SELECT_PATTERN.finditer(data)):
        if index >= _DESKI_MATCH_LIMIT:
            warnings.append("SQL marker scan reached its limit.")
            break
        if match.start() < accepted_until:
            continue
        whitespace = 0
        while (whitespace < 16 and match.start() > whitespace
               and data[match.start() - whitespace - 1] in b" \t\r\n"):
            whitespace += 1
        frames = []
        for leading in range(whitespace + 1):
            prefix = match.start() - leading - 2
            if prefix < 0:
                continue
            length = int.from_bytes(data[prefix:prefix + 2], "little")
            start = prefix + 2
            end = start + length
            if length < leading + 6 or end > len(data):
                continue
            if length > scan_budget:
                warnings.append("SQL frame inspection reached its byte limit.")
                return candidates
            scan_budget -= length
            raw = data[start:end]
            try:
                sql = raw.decode("utf-8")
            except UnicodeDecodeError:
                undecodable = True
                continue
            if (not re.match(r"\s*SELECT\b", sql, re.IGNORECASE)
                    or not _DESKI_FROM_PATTERN.search(sql)
                    or any(not character.isprintable() and character not in "\t\r\n"
                           for character in sql)):
                continue
            frames.append((start, end, sql))
        if len(frames) > 1:
            warnings.append("An ambiguous length-framed SQL candidate was skipped.")
            continue
        if not frames:
            continue
        start, end, sql = frames[0]
        accepted_until = end
        prior = [provider for provider in provider_items
                 if provider["stream_offset"] < start]
        provider_id = prior[-1]["id"] if can_associate and prior else None
        calls = sorted({item.group(1).lower() for item in _DESKI_BO_CALL_PATTERN.finditer(sql)})
        literals = [
            {"function": item.group(1).lower(), "literal": item.group(2).replace("''", "'")}
            for item in _DESKI_LITERAL_CALL_PATTERN.finditer(sql)
        ]
        candidates.append({
            "sql": sql, "sql_status": "unverified", "stream": _DESKI_PROVIDER_STREAM,
            "stream_offset": start, "byte_length": end - start,
            "possible_provider_id": provider_id,
            "provider_association": (
                "nearest_preceding_header_unverified" if provider_id else "unresolved"
            ),
            "bo_function_markers": calls, "literal_arguments": literals,
        })
    if undecodable:
        warnings.append("Some possible SQL frames are not UTF-8; they were not decoded.")
    if any(item["bo_function_markers"] for item in candidates):
        warnings.append("BO function markers in SQL require separate review and translation.")
    if not candidates:
        warnings.append("No framed SELECT/FROM candidate was recovered from the provider list.")
    return candidates


def _deski_objects(data, warnings):
    objects = []
    undecodable = False
    for index, match in enumerate(_DESKI_PROVIDER_PATTERN.finditer(data)):
        if index >= _DESKI_MATCH_LIMIT:
            warnings.append("Dictionary marker scan reached its limit.")
            break
        offset = match.start()
        if offset < 2 or int.from_bytes(data[offset - 2:offset], "little") != len(match.group()):
            continue
        provider_id = match.group().decode("ascii")
        try:
            identifier, position = _deski_lp_text(data, match.end() + 4)
            accessor, separator, _ = identifier.partition(".")
            if not separator or not re.fullmatch(re.escape(provider_id) + r"DAC[0-9]+#[0-9]+",
                                                 accessor):
                continue
            name, position = _deski_lp_text(data, position)
            alias, position = _deski_lp_text(data, position)
            actual_accessor, _ = _deski_lp_text(data, position)
        except UnicodeDecodeError:
            undecodable = True
            continue
        except ValueError:
            continue
        if name and actual_accessor == accessor:
            objects.append({
                "name": name, "alias": alias, "source_identifier": identifier,
                "possible_provider_id": provider_id, "stream": _DESKI_DICTIONARY_STREAM,
                "stream_offset": offset - 2,
            })
    if undecodable:
        warnings.append("Some dictionary strings are not UTF-8; they were not decoded.")
    return objects


def _deski_formulas(data, stream, warnings):
    formulas = []
    scan_budget = _DESKI_SCAN_LIMIT
    accepted_until = 0
    undecodable = False
    for index, match in enumerate(re.finditer(b"=", data)):
        if index >= _DESKI_MATCH_LIMIT:
            warnings.append(f"Formula marker scan reached its limit in {stream}.")
            break
        offset = match.start()
        if offset < 2 or offset < accepted_until:
            continue
        length = int.from_bytes(data[offset - 2:offset], "little")
        end = offset + length
        if not length or end > len(data):
            continue
        if length > scan_budget:
            warnings.append(f"Formula frame inspection reached its byte limit in {stream}.")
            break
        scan_budget -= length
        try:
            text = data[offset:end].decode("utf-8")
        except UnicodeDecodeError:
            undecodable = True
            continue
        if any(not character.isprintable() and character not in "\t\r\n" for character in text):
            continue
        formulas.append({"expression": text, "stream": stream, "stream_offset": offset})
        accepted_until = end
    if undecodable:
        warnings.append(f"Some possible formula frames in {stream} are not UTF-8.")
    return formulas


def desktop_intelligence_sql_selector(candidate):
    """Return the standalone paginated CLI selector for a SQL candidate."""
    provider_id = candidate["possible_provider_id"] or "unresolved"
    return f"{provider_id}@{candidate['stream_offset']}"


def desktop_intelligence_formula_selector(candidate):
    """Return a stream-local review reference for a formula candidate."""
    return f"{candidate['stream']}@{candidate['stream_offset']}"


def inspect_desktop_intelligence(path):
    """Return a partial static REP inventory, not migration-ready BO objects."""
    source = Path(path)
    if source.suffix.lower() != ".rep":
        raise ValueError("Desktop Intelligence input must have a .rep extension")
    digest, size, signature = _deski_hash_file(source)
    if zipfile.is_zipfile(source):
        container = "zip"
        storage = _DeskiZipStorage(source)
    elif signature == _DESKI_OLE_SIGNATURE:
        container = "ole"
        storage = _DeskiOleStorage(source)
    else:
        raise ValueError("unsupported REP container; expected ZIP or OLE")

    warnings = [
        "Experimental partial inventory: candidates, associations and completeness are unverified.",
        "SQL and other extracted metadata can contain sensitive information; protect this output.",
    ]
    with storage:
        provider_data = storage.read(_DESKI_PROVIDER_STREAM)
        sheet_data = storage.read(_DESKI_SHEETS_STREAM)
        if provider_data is None or sheet_data is None:
            raise ValueError("REP lacks required provider-list or sheet-list streams")
        dictionary = storage.read(_DESKI_DICTIONARY_STREAM)
        alerters = storage.read("AlerterManager;")
        version = _deski_version(storage.read("FormatVersion"), "FormatVersion", warnings)
        earliest = _deski_version(
            storage.read("EarliestCompatibleFormatVersion"),
            "EarliestCompatibleFormatVersion", warnings,
        )
        sheets = _deski_sheets(sheet_data, warnings)
        providers = _deski_providers(provider_data, warnings)
        for provider in providers["candidates"]:
            stream_name = f"GDM|/{provider['id']}|/Query;"
            query_data = storage.read(stream_name)
            if query_data is None:
                if provider["provider_type_marker"] == "DPQTC":
                    warnings.append(f"Missing optional query metadata stream for {provider['id']}.")
                continue
            metadata = _deski_query_metadata(query_data, stream_name, warnings)
            if metadata is not None:
                provider["query_metadata_candidate"] = metadata
        sql = _deski_sql(provider_data, providers, warnings)
        objects = []
        formulas = []
        if dictionary is None:
            warnings.append("Missing optional dictionary stream; objects and formulas are incomplete.")
        else:
            objects = _deski_objects(dictionary, warnings)
            formulas.extend(_deski_formulas(dictionary, _DESKI_DICTIONARY_STREAM, warnings))
        if alerters is None:
            warnings.append("Missing optional alerter stream.")
        else:
            formulas.extend(_deski_formulas(alerters, "AlerterManager;", warnings))
        visual_cache = {}
        for sheet in sheets["candidates"]:
            storage_name = sheet["storage"]
            if not re.fullmatch(r"ReportSheet[0-9]{1,8}", storage_name):
                warnings.append("A sheet storage name was not recognized; its format was not read.")
                continue
            stream_name = f"ReportSheets|/{storage_name}|/Data ReportFmt;"
            if stream_name not in visual_cache:
                visual_cache[stream_name] = storage.read(stream_name)
            visual = visual_cache[stream_name]
            if visual is None:
                warnings.append(f"Missing optional report-format stream for {storage_name}.")
                continue
            sheet["structure_markers"] = [
                marker.decode("ascii") for marker in _DESKI_VISUAL_MARKERS if marker in visual
            ]
    if _deski_hash_file(source)[:2] != (digest, size):
        raise ValueError("REP changed while it was inspected")
    return {
        "schema_version": 1,
        "evidence_boundary": "experimental_partial_static_inventory",
        "status": "partial",
        "source": {"file_name": source.name, "size_bytes": size,
                   "sha256": digest, "container": container},
        "format_version": version,
        "earliest_compatible_format_version": earliest,
        "sheets": sheets,
        "providers": providers,
        "object_candidates": objects,
        "sql_candidates": sql,
        "formula_candidates": formulas,
        "warnings": warnings,
        "not_run": ["desktop_intelligence_open", "macro_execution", "query_execution",
                    "report_rendering", "source_target_equivalence"],
    }
