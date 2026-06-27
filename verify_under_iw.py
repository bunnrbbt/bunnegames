#!/usr/bin/env python3
"""Validate a page still loads in ONE round trip via the TCP Initial Window.

The "1 packet" budget (verify_one_packet.py) is the strict flex. This is the
relaxed one: a response fits in one round trip as long as it fits inside the
server's initial congestion window -- the burst it may send before waiting for
an ACK. RFC 6928 sets that to 10 segments, i.e. 10 x 1460 = 14600 bytes.

Same two checks as the 1-packet validator:
  1. zero external subresources (otherwise the browser needs more round trips),
  2. the full brotli HTTP/2 response, on the wire, fits the initial window.

Usage:  python3 verify_under_iw.py [path]   (default: index.html)
Exit:   0 = PASS, 1 = FAIL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verify_one_packet import (  # noqa: E402  reuse the measurement plumbing
    HPACK_HEADERS, MSS, brotli_compress, external_subresources, tls_wire_size,
)

IW_SEGMENTS = 10            # RFC 6928 initial congestion window
IW = IW_SEGMENTS * MSS      # 14600 B sendable in the first round trip


def main(path: str) -> int:
    raw = Path(path).read_bytes()
    html = raw.decode("utf-8", "replace")
    br = brotli_compress(raw)
    print(f"page: {path}  ({len(raw)} B raw, {len(br)} B brotli)\n")

    ok = True

    hits = external_subresources(html)
    if hits:
        ok = False
        print("FAIL  external subresources (each adds a round trip):")
        for label, ctx in hits:
            print(f"        - {label}: {ctx!r}")
    else:
        print("PASS  no external subresources -> everything ships in one response")

    response = bytes(9) + bytes(HPACK_HEADERS) + bytes(9) + br
    try:
        wire = tls_wire_size(response)
        how = "real TLS 1.3"
    except Exception:
        wire = len(response) + 22
        how = "estimated (openssl unavailable)"
    packets = -(-wire // MSS)  # ceil
    margin = IW - wire
    verdict = "PASS" if wire <= IW else "FAIL"
    if wire > IW:
        ok = False
    print(f"\n{verdict}  full response on the wire: {wire} B "
          f"(~{packets} of {IW_SEGMENTS} packets, {how})")
    print(f"        initial window {IW} B ({IW_SEGMENTS} x {MSS}), margin {margin:+d} B")

    print("\n" + ("==> PASS: fits the initial congestion window (1 round trip)"
                  if ok else "==> FAIL: exceeds the initial window"))
    return 0 if ok else 1


if __name__ == "__main__":
    default = str(Path(__file__).with_name("index.html"))
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else default))
