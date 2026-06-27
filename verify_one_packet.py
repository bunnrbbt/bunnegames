#!/usr/bin/env python3
"""Verify the homepage loads in a single network round trip ("1 trip").

Two things must hold:

  1. ZERO external subresources. The page must render from one HTTP response,
     so the browser makes exactly one request. No external CSS / JS / fonts /
     images / resource hints. (The favicon is an inline data: URI, so it costs
     no fetch.)

  2. That one response, brotli-compressed, fits in a SINGLE TCP packet
     (<=1460 B), including the HTTP/2 response headers + TLS 1.3 framing.

We only care about brotli: every modern browser negotiates it over HTTPS, and
all major static hosts serve it. The gzip fallback is knowingly ~2 packets and
is not checked here (still one round trip either way).

Usage:  python3 verify_one_packet.py [path]   (default: minimal.html)
Exit:   0 = PASS, 1 = FAIL.
"""
import os
import re
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PAGE = Path(__file__).with_name("minimal.html")  # the strict 1-packet build
MSS = 1460           # TCP payload on a 1500-byte-MTU link (1500 - 20 IP - 20 TCP)
HPACK_HEADERS = 130  # conservative HPACK-compressed response header block (header-heavy host)


def brotli_compress(data: bytes) -> bytes:
    try:
        import brotli  # python-brotli, if installed
        return brotli.compress(data, quality=11)
    except ImportError:
        pass
    try:
        return subprocess.run(
            ["brotli", "-q", "11", "-c"], input=data, capture_output=True, check=True
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit("error: need the 'brotli' python module or the 'brotli' CLI")


def external_subresources(html: str):
    """Anything the browser must fetch to render the page (each = a round trip)."""
    # collapse data: URIs so an inline favicon/SVG can't trip the scanners
    scan = re.sub(r'data:[^"\')\s]*', "data:", html)
    patterns = [
        (r'<link[^>]+rel=["\']?stylesheet', "external stylesheet"),
        (r'<link[^>]+rel=["\']?(?:preload|prefetch|preconnect|dns-prefetch)',
         "resource hint (extra connection)"),
        (r'<script[^>]+\bsrc=', "external script"),
        (r'<img[^>]+\bsrc=["\']?(?!data:)', "external image"),
        (r'<(?:iframe|video|audio|source)[^>]+\bsrc=["\']?(?!data:)', "external media"),
        (r'@import', "css @import"),
        (r'url\(\s*["\']?(?!data:)', "css url() (external asset/font)"),
    ]
    hits = []
    for pat, label in patterns:
        for m in re.finditer(pat, scan, re.I):
            hits.append((label, scan[m.start():m.start() + 60].replace("\n", " ")))
    return hits


def tls_wire_size(app: bytes) -> int:
    """Encrypt `app` through a real TLS 1.3 session; return bytes put on the wire."""
    d = tempfile.mkdtemp()
    key, crt = os.path.join(d, "k"), os.path.join(d, "c")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
         "-out", crt, "-days", "1", "-nodes", "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(crt, key)
    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.check_hostname = False
    cctx.verify_mode = ssl.CERT_NONE
    si, so = ssl.MemoryBIO(), ssl.MemoryBIO()
    ci, co = ssl.MemoryBIO(), ssl.MemoryBIO()
    srv = sctx.wrap_bio(si, so, server_side=True)
    cli = cctx.wrap_bio(ci, co)
    for _ in range(10):
        for obj, src, dst in ((cli, co, si), (srv, so, ci)):
            try:
                obj.do_handshake()
            except ssl.SSLWantReadError:
                pass
            chunk = src.read()
            if chunk:
                dst.write(chunk)
        if cli.cipher() and srv.cipher():
            break
    srv.write(app)
    return len(so.read())


def main(page: Path) -> int:
    raw = page.read_bytes()
    html = raw.decode("utf-8", "replace")
    br = brotli_compress(raw)
    print(f"page: {page.name}  ({len(raw)} B raw, {len(br)} B brotli)\n")

    ok = True

    # ---- check 1: exactly one request -------------------------------------
    hits = external_subresources(html)
    if hits:
        ok = False
        print("FAIL  external subresources (each adds a round trip):")
        for label, ctx in hits:
            print(f"        - {label}: {ctx!r}")
    else:
        print("PASS  no external subresources -> page renders from one response")

    # ---- check 2: exactly one packet (brotli) -----------------------------
    # HTTP/2 response = HEADERS frame (9 B + HPACK) + DATA frame (9 B + body)
    response = bytes(9) + bytes(HPACK_HEADERS) + bytes(9) + br
    try:
        wire = tls_wire_size(response)
        how = "real TLS 1.3"
    except (FileNotFoundError, subprocess.CalledProcessError):
        wire = len(response) + 22  # TLS 1.3 record overhead, if openssl is missing
        how = "estimated (openssl unavailable)"
    margin = MSS - wire
    verdict = "PASS" if wire <= MSS else "FAIL"
    if wire > MSS:
        ok = False
    print(f"\n{verdict}  full HTTP/2 response on the wire: {wire} B "
          f"({how}, {HPACK_HEADERS} B headers)")
    print(f"        budget {MSS} B (one TCP packet), margin {margin:+d} B")

    print("\n" + ("==> PASS: homepage is exactly 1 trip"
                  if ok else "==> FAIL: homepage is NOT 1 trip"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PAGE))
