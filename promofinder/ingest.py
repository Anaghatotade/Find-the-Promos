"""Load a show from a ZIP, a directory, or individual .txt files (safely)."""
from __future__ import annotations
import hashlib, io, os, zipfile, zlib
from typing import Dict, Iterable, List, Optional, Tuple
from .parser import parse_screenplay, Episode

MAX_FILE_BYTES = 5_000_000      # per screenplay file
MAX_FILES = 2000
MAX_TOTAL_BYTES = 80_000_000    # total decompressed text accepted from one upload


class InputError(ValueError):
    """A problem with what the user supplied (shown to them verbatim, never a stack trace)."""


def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "ignore")


def _read_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, zip_name: str) -> bytes:
    """Return the bytes of one file inside the ZIP. Damaged members, unsupported compression (e.g. Deflate64)
    and encryption raise InputError with a message the user can act on, instead of a raw exception."""
    zn, fn = os.path.basename(zip_name), info.filename
    if info.flag_bits & 0x1:
        raise InputError(f"'{zn}' is password-protected ('{fn}'). Upload an unencrypted ZIP, or select the episode .txt files directly.")
    try:
        # read with a hard cap: a member whose header under-states its size (zip bomb) is cut off
        with z.open(info) as fh:
            return fh.read(MAX_FILE_BYTES + 1)
    except NotImplementedError:
        method = {9: "Deflate64", 12: "BZIP2", 14: "LZMA", 95: "XZ", 98: "PPMd", 99: "AES"}.get(info.compress_type, f"#{info.compress_type}")
        raise InputError(f"'{zn}' uses {method} compression, which PromoFinder can't read ('{fn}'). Re-create the ZIP with standard "
                         "(Deflate) compression, or select all the episode .txt files and upload them directly.")
    except RuntimeError as e:   # encrypted members not flagged in the header
        raise InputError(f"'{zn}' could not be read ('{fn}': {e}). Upload an unencrypted ZIP or the .txt files directly.")
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as e:
        raise InputError(f"'{zn}' is damaged: '{fn}' failed its integrity check ({type(e).__name__}). "
                         "Download or create the ZIP again, or upload the episode .txt files directly.")


def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except LookupError:
        # Non-UTF-8 member names are decoded with the cp437 codec, which some Python installs
        # fail to load. latin-1 is built in and maps every byte, so names still decode.
        return zipfile.ZipFile(io.BytesIO(data), metadata_encoding="latin-1")


def _iter_zip(data: bytes, zip_name: str = "upload.zip") -> Iterable[Tuple[str, bytes]]:
    try:
        z = _open_zip(data)
    except zipfile.BadZipFile:
        raise InputError(f"'{os.path.basename(zip_name)}' is not a valid ZIP archive (it may be corrupted or still downloading).")
    with z:
        if len(z.infolist()) > MAX_FILES:
            raise InputError(f"'{os.path.basename(zip_name)}' contains more than {MAX_FILES} files.")
        total = 0
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or not name.lower().endswith(".txt"):
                continue
            if "__MACOSX" in name or os.path.basename(name).startswith("."):
                continue
            if info.file_size > MAX_FILE_BYTES:
                continue
            data = _read_member(z, info, zip_name)
            if len(data) > MAX_FILE_BYTES:
                continue
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise InputError(f"'{os.path.basename(zip_name)}' expands to more than {MAX_TOTAL_BYTES // 1_000_000} MB of text.")
            yield name, data


def load_inputs(paths: List[str]) -> Tuple[str, List[Episode]]:
    """Accepts any mix of .zip / directories / .txt. Returns (show_name, episodes)."""
    items: List[Tuple[str, bytes]] = []
    show = None
    for p in paths:
        if os.path.isdir(p):
            show = show or os.path.basename(os.path.normpath(p))
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.lower().endswith(".txt"):
                        with open(os.path.join(root, f), "rb") as fh:
                            items.append((os.path.join(root, f), fh.read()))
        elif p.lower().endswith(".zip"):
            with open(p, "rb") as fh:
                zitems = list(_iter_zip(fh.read(), p))
            items.extend(zitems)
            if zitems and show is None:
                d = os.path.dirname(zitems[0][0])
                show = os.path.basename(d) if d else os.path.splitext(os.path.basename(p))[0]
        elif p.lower().endswith(".txt"):
            with open(p, "rb") as fh:
                items.append((p, fh.read()))
    return load_bytes(items, show)


def load_bytes(items: List[Tuple[str, bytes]], show: str | None = None,
               report: Optional[Dict[str, list]] = None) -> Tuple[str, List[Episode]]:
    """Parse uploaded files. If `report` is given it receives lists of skipped files and
    load warnings, so a UI can explain what happened instead of failing silently."""
    report = report if report is not None else {}
    report.setdefault("skipped", []); report.setdefault("warnings", [])
    expanded: List[Tuple[str, bytes]] = []
    for name, data in items:
        if name.lower().endswith(".zip"):
            z = list(_iter_zip(data, name)); expanded.extend(z)
            if z and not show:
                show = os.path.basename(os.path.dirname(z[0][0])) or os.path.splitext(os.path.basename(name))[0]
        else:
            expanded.append((name, data))
    # identical files uploaded twice (e.g. the ZIP and a loose .txt) are dropped, not double-counted
    seen_hash, uniq = set(), []
    for n, d in expanded:
        h = hashlib.sha1(d).hexdigest()
        if h in seen_hash:
            report["warnings"].append(f"duplicate file ignored: {os.path.basename(n)}")
            continue
        seen_hash.add(h); uniq.append((n, d))
    eps = []
    for n, d in uniq:
        e = parse_screenplay(_decode(d), os.path.basename(n))
        if e.blocks:
            eps.append(e)
        else:
            report["skipped"].append(os.path.basename(n))
    eps.sort(key=lambda e: (e.number, e.src_file))
    # unknown or clashing episode numbers go AFTER the highest real number, so real episodes keep their identity
    seen, nxt = set(), max((e.number for e in eps), default=0) + 1
    for e in eps:
        if e.number in seen or e.number <= 0:
            report["warnings"].append(f"{e.src_file}: episode number {e.number} missing or duplicated; treated as episode {nxt}")
            e.warnings.append(f"episode number {e.number} ambiguous; renumbered to {nxt}")
            e.number = nxt; nxt += 1
            for b in e.blocks:
                b.episode = e.number
        seen.add(e.number)
    eps.sort(key=lambda e: e.number)
    return (show or "Untitled show"), eps
