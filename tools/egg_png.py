#!/usr/bin/env python3
"""egg_png.py -- Easter-egg sweep of a PNG file, deterministically.

Three questions, answered from the bytes and never by eye:

  1. Chunk walk: every chunk type with length and CRC validity; all
     tEXt / zTXt / iTXt strings verbatim; IHDR fields.
  2. Trailing bytes after IEND: exact count, printable render if any.
     Nonzero trailing bytes would be a real finding.
  3. LSB statistics (low priority): per channel, the LSB-plane 1-fraction
     and a byte-level Shannon entropy for the packed LSB plane, with
     bit-plane 1 reported beside it as the internal control. Numbers only;
     an extraction attempt is reported only as a printable fraction.

Modes:
  egg_png.py <file.png>       analyse a file
  egg_png.py --selftest       tiny in-memory PNG with a planted tEXt chunk
                              and 8 trailing bytes; both must be reported
  egg_png.py --control        fixed-seed random RGBA PNG through the same
                              LSB analysis, to show what noise scores

Stdlib only (zlib, struct). No image library: IDAT is inflated and
de-filtered here, so the pixel path is auditable.
"""

import argparse
import math
import struct
import sys
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"

COLOR_TYPE_NAMES = {
    0: "greyscale",
    2: "truecolor (RGB)",
    3: "indexed",
    4: "greyscale+alpha",
    6: "truecolor+alpha (RGBA)",
}

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


# ---------------------------------------------------------------- chunk walk

def walk_chunks(data):
    """Yield (offset, type, length, crc_ok, chunk_data). Stops after IEND;
    the caller measures what is left."""
    if data[:8] != PNG_SIG:
        raise ValueError("not a PNG: signature mismatch")
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        crc_stored = data[pos + 8 + length:pos + 12 + length]
        if len(body) < length or len(crc_stored) < 4:
            yield pos, ctype, length, False, body
            pos = len(data)
            break
        crc_ok = struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF) == crc_stored
        yield pos, ctype, length, crc_ok, body
        pos += 12 + length
        if ctype == b"IEND":
            break
    walk_chunks.end_offset = pos  # first byte after the IEND chunk


def parse_ihdr(body):
    w, h, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", body[:13])
    return dict(width=w, height=h, bit_depth=depth, color_type=ctype,
                compression=comp, filter=filt, interlace=interlace)


def decode_text_chunk(ctype, body):
    """Return a list of (kind, keyword, text) for tEXt/zTXt/iTXt."""
    try:
        if ctype == b"tEXt":
            k, _, v = body.partition(b"\x00")
            return [("tEXt", k.decode("latin-1"), v.decode("latin-1"))]
        if ctype == b"zTXt":
            k, _, rest = body.partition(b"\x00")
            method, comp = rest[0], rest[1:]
            text = zlib.decompress(comp).decode("latin-1") if method == 0 else "<unknown compression method %d>" % method
            return [("zTXt", k.decode("latin-1"), text)]
        if ctype == b"iTXt":
            k, _, rest = body.partition(b"\x00")
            comp_flag, comp_method = rest[0], rest[1]
            rest = rest[2:]
            lang, _, rest = rest.partition(b"\x00")
            tkey, _, rest = rest.partition(b"\x00")
            text = zlib.decompress(rest) if comp_flag else rest
            return [("iTXt", k.decode("utf-8", "replace"),
                     "[lang=%s tkey=%s] %s" % (lang.decode("utf-8", "replace"),
                                               tkey.decode("utf-8", "replace"),
                                               text.decode("utf-8", "replace")))]
    except Exception as exc:  # malformed chunk is itself worth reporting
        return [(ctype.decode("latin-1"), "<parse error>", repr(exc))]
    return []


# ---------------------------------------------------------------- de-filter

def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def defilter(raw, width, height, channels, depth):
    """8-bit-per-sample de-filter. Returns bytearray of width*height*channels."""
    if depth != 8:
        raise ValueError("de-filter implemented for bit depth 8 only (got %d)" % depth)
    bpp = channels
    stride = width * channels
    out = bytearray(stride * height)
    pos = 0
    prev_row = bytearray(stride)
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + stride])
        pos += stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                ul = prev_row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + paeth(left, prev_row[i], ul)) & 0xFF
        else:
            raise ValueError("unknown filter type %d at row %d" % (ftype, y))
        out[y * stride:(y + 1) * stride] = row
        prev_row = row
    return out


# ---------------------------------------------------------------- bit planes

def shannon_entropy(byte_seq):
    if not byte_seq:
        return 0.0
    counts = [0] * 256
    for b in byte_seq:
        counts[b] += 1
    n = len(byte_seq)
    ent = 0.0
    for c in counts:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    return ent


def pack_bits(bits):
    """Pack an iterable of 0/1 into bytes, MSB first."""
    out = bytearray()
    acc = 0
    n = 0
    for bit in bits:
        acc = (acc << 1) | bit
        n += 1
        if n == 8:
            out.append(acc)
            acc = 0
            n = 0
    return bytes(out)


def plane_stats(pixels, channels, plane):
    """Per-channel 1-fraction for bit `plane`, plus entropy and printable
    fraction of the packed all-channels-interleaved plane."""
    ones = [0] * channels
    total = len(pixels) // channels
    mask = 1 << plane
    bits = []
    for i, b in enumerate(pixels):
        bit = 1 if b & mask else 0
        ones[i % channels] += bit
        bits.append(bit)
    packed = pack_bits(bits)
    printable = sum(1 for b in packed if 32 <= b < 127 or b in (9, 10, 13))
    return dict(
        per_channel_one_fraction=[round(o / total, 4) for o in ones],
        packed_entropy_bits_per_byte=round(shannon_entropy(packed), 4),
        packed_printable_fraction=round(printable / len(packed), 4) if packed else 0.0,
        packed_len=len(packed),
    )


# ---------------------------------------------------------------- analysis

def analyse(data, label, do_lsb=True):
    print("== %s ==" % label)
    ihdr = None
    idat = bytearray()
    findings = []

    chunks = list(walk_chunks(data))
    end = walk_chunks.end_offset
    print("chunks:")
    for off, ctype, length, crc_ok, body in chunks:
        name = ctype.decode("latin-1", "replace")
        print("  %-6s off=%-8d len=%-8d crc=%s" % (name, off, length, "OK" if crc_ok else "BAD"))
        if not crc_ok:
            findings.append("chunk %s at offset %d has a BAD CRC" % (name, off))
        if ctype == b"IHDR":
            ihdr = parse_ihdr(body)
        elif ctype == b"IDAT":
            idat.extend(body)
        for kind, key, text in decode_text_chunk(ctype, body):
            print("  TEXT [%s] keyword=%r text=%r" % (kind, key, text))
            findings.append("text chunk %s: keyword=%r text=%r" % (kind, key, text))

    if ihdr:
        print("IHDR: %dx%d, bit depth %d, color type %d (%s), interlace %d" % (
            ihdr["width"], ihdr["height"], ihdr["bit_depth"], ihdr["color_type"],
            COLOR_TYPE_NAMES.get(ihdr["color_type"], "?"), ihdr["interlace"]))

    trailing = data[end:]
    print("trailing bytes after IEND: %d" % len(trailing))
    if trailing:
        printable = "".join(chr(b) if 32 <= b < 127 else "." for b in trailing[:512])
        print("  printable render (first 512): %r" % printable)
        findings.append("%d trailing bytes after IEND" % len(trailing))

    if do_lsb and ihdr and ihdr["color_type"] in CHANNELS and ihdr["bit_depth"] == 8 \
            and ihdr["interlace"] == 0 and idat:
        channels = CHANNELS[ihdr["color_type"]]
        raw = zlib.decompress(bytes(idat))
        pixels = defilter(raw, ihdr["width"], ihdr["height"], channels, ihdr["bit_depth"])
        for plane in (0, 1):
            st = plane_stats(pixels, channels, plane)
            tag = "LSB plane (bit 0)" if plane == 0 else "bit plane 1 (control)"
            print("%s: per-channel 1-fraction=%s entropy=%.4f bits/byte "
                  "printable-fraction=%.4f over %d packed bytes" % (
                      tag, st["per_channel_one_fraction"],
                      st["packed_entropy_bits_per_byte"],
                      st["packed_printable_fraction"], st["packed_len"]))
    elif do_lsb:
        print("LSB analysis skipped (unsupported format for this decoder)")

    print("findings: %d" % len(findings))
    for f in findings:
        print("  * %s" % f)
    print()
    return findings


# ---------------------------------------------------------------- builders

def build_png(width, height, pixel_bytes, extra_chunks=(), trailing=b""):
    """Assemble a valid RGBA PNG from raw pixel bytes (no filtering)."""
    def chunk(ctype, body):
        return (struct.pack(">I", len(body)) + ctype + body +
                struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    stride = width * 4
    raw = b"".join(b"\x00" + pixel_bytes[y * stride:(y + 1) * stride] for y in range(height))
    out = bytearray(PNG_SIG)
    out += chunk(b"IHDR", ihdr)
    for ctype, body in extra_chunks:
        out += chunk(ctype, body)
    out += chunk(b"IDAT", zlib.compress(raw))
    out += chunk(b"IEND", b"")
    out += trailing
    return bytes(out)


def selftest():
    """Planted tEXt chunk + 8 trailing bytes: both must be reported."""
    pixels = bytes((x * 37 + y * 91 + c * 13) & 0xFF
                   for y in range(4) for x in range(4) for c in range(4))
    png = build_png(4, 4, pixels,
                    extra_chunks=[(b"tEXt", b"Egg\x00planted-selftest-string")],
                    trailing=b"TRAILING")
    findings = analyse(png, "selftest (in-memory 4x4 RGBA)")
    ok_text = any("planted-selftest-string" in f for f in findings)
    ok_trail = any("8 trailing bytes" in f for f in findings)
    print("selftest tEXt reported:      %s" % ("PASS" if ok_text else "FAIL"))
    print("selftest trailing reported:  %s" % ("PASS" if ok_trail else "FAIL"))
    return 0 if (ok_text and ok_trail) else 1


def control():
    """Fixed-seed random RGBA noise through the same LSB analysis.
    This is what an unstructured image scores; compare the target to it."""
    import random
    rng = random.Random(424242)
    w, h = 64, 64
    pixels = bytes(rng.randrange(256) for _ in range(w * h * 4))
    findings = analyse(build_png(w, h, pixels), "control (fixed-seed random 64x64 RGBA)")
    # a control must be quiet: no text chunks, no trailing bytes
    return 0 if not findings else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="PNG file to analyse")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--no-lsb", action="store_true", help="skip pixel decode")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if args.control:
        sys.exit(control())
    if not args.path:
        ap.error("give a PNG path, or --selftest / --control")
    with open(args.path, "rb") as fh:
        data = fh.read()
    analyse(data, args.path, do_lsb=not args.no_lsb)
    sys.exit(0)


if __name__ == "__main__":
    main()
