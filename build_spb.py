#!/usr/bin/env python3
"""
Build an MSFS InGamePanel .spb file by patching an existing one.

SPB format (SimPropBinary):
  Header: UInt16 magic (0xEBAC) + 12 x Int32 (header[6] = ntags)
  Tag defs: (ntags-1) entries of 16-byte GUID + Int32 flag
  Data: recursive tag_number(Int32) + value

Flag = byte size of value: 4=Int32/Float, 8=Long2/Double, 16=GUID, -1=variable(size-prefixed)
Variable-length: Int32 size, then 'size' bytes (SET or encoded TEXT)
"""

import re
import struct
import sys
import os
import uuid as uuid_mod

# ── TextDecode substitution cipher ──

def parse_textdecode_cs(filepath):
    S = [None] * 256
    with open(filepath, 'r') as f:
        content = f.read()
    for m in re.finditer(r'S\[0x([0-9A-Fa-f]+)\]\s*=\s*new\s+byte\[\]\s*\{([^}]+)\}', content):
        idx = int(m.group(1), 16)
        S[idx] = [int(b.strip(), 0) for b in m.group(2).strip().split(',') if b.strip()]
    return S


def build_K_table(S):
    K = [[0xFF] * 250 for _ in range(256)]
    for i in range(256):
        if S[i] is not None:
            for j in range(len(S[i])):
                K[S[i][j]][j] = i
    return K


def text_encode(S, text):
    result = bytearray(len(text) + 1)
    for i, ch in enumerate(text):
        row = S[ord(ch)]
        if row is None:
            raise ValueError(f"Char {ch!r} not in table")
        result[i] = row[i % 250]
    result[len(text)] = S[0][len(text) % 250]
    return bytes(result)


def text_decode(K, encoded):
    if len(encoded) == 0:
        return ""
    chars = []
    for i in range(len(encoded) - 1):
        ch = K[encoded[i]][i % 250]
        if ch == 0xFF:
            return None
        chars.append(chr(ch))
    if K[encoded[-1]][(len(encoded)-1) % 250] != 0:
        return None
    return ''.join(chars)


# ── SPB parser ──

MAGIC = 0xEBAC

def read_spb(filepath):
    with open(filepath, 'rb') as f:
        return f.read()


def parse_header(data):
    magic = struct.unpack_from('<H', data, 0)[0]
    assert magic == MAGIC
    headers = [struct.unpack_from('<i', data, 2 + i*4)[0] for i in range(12)]
    pos = 50
    tags = []
    for _ in range(headers[6] - 1):
        guid = data[pos:pos+16]
        flag = struct.unpack_from('<i', data, pos+16)[0]
        tags.append((guid, flag))
        pos += 20
    return headers, tags, pos


def walk(data, pos, end, tags, K, depth=0):
    """Parse data section. Returns (results_list, final_pos)."""
    pre = "  " * depth
    results = []
    while pos < end:
        if pos + 4 > end:
            break
        tag_num = struct.unpack_from('<i', data, pos)[0]
        pos += 4
        if tag_num == 0:
            results.append((-2, 'zero', b'\x00\x00\x00\x00'))
            continue
        ti = tag_num - 1
        if ti < 0 or ti >= len(tags):
            print(f"{pre}ERR tag_num={tag_num} @0x{pos-4:04X}")
            pos -= 4
            break
        _, flag = tags[ti]

        if flag == -1:
            sz = struct.unpack_from('<i', data, pos)[0]
            pos += 4
            blob = data[pos:pos+sz]
            txt = text_decode(K, blob) if sz > 0 else ""
            if txt is not None:
                print(f"{pre}TEXT[{ti}] = {txt!r}")
                results.append((ti, 'text', txt))
            else:
                print(f"{pre}SET[{ti}] {{")
                children, cpos = walk(data, pos, pos+sz, tags, K, depth+1)
                tail = data[cpos:pos+sz]
                if tail:
                    print(f"{pre}  TAIL({len(tail)}B): {tail.hex()}")
                    children.append((-1, 'tail', tail))
                results.append((ti, 'set', children))
                print(f"{pre}}}")
            pos += sz
        elif flag == 4:
            vi = struct.unpack_from('<i', data, pos)[0]
            vf = struct.unpack_from('<f', data, pos)[0]
            pos += 4
            if vi in (0, 1) and (vf == 0.0 or vf == 1.4012984643248171e-45):
                print(f"{pre}BOOL[{ti}] = {bool(vi)}")
                results.append((ti, 'bool', vi))
            elif abs(vf) > 0.001 and abs(vf) < 100000:
                print(f"{pre}FLOAT[{ti}] = {vf:.3f}")
                results.append((ti, 'float', vf))
            else:
                print(f"{pre}INT[{ti}] = {vi}")
                results.append((ti, 'int', vi))
        elif flag == 8:
            v1, v2 = struct.unpack_from('<ii', data, pos)
            pos += 8
            print(f"{pre}LONG2[{ti}] = ({v1},{v2})")
            results.append((ti, 'long2', (v1, v2)))
        elif flag == 0x10:
            gb = data[pos:pos+16]
            pos += 16
            print(f"{pre}GUID[{ti}] = {uuid_mod.UUID(bytes_le=gb)}")
            results.append((ti, 'guid', gb))
        else:
            n = abs(flag) if flag > 0 else 4
            rb = data[pos:pos+n]
            pos += n
            print(f"{pre}RAW[{ti}] f={flag} = {rb.hex()}")
            results.append((ti, 'raw', rb))
    return results, pos


def build_data(tree, tags, S):
    buf = bytearray()
    for ti, typ, val in tree:
        if ti == -1 and typ == 'tail':
            buf += val
            continue
        if ti == -2 and typ == 'zero':
            buf += val
            continue
        buf += struct.pack('<i', ti + 1)
        _, flag = tags[ti]
        if typ == 'text':
            enc = text_encode(S, val)
            buf += struct.pack('<i', len(enc))
            buf += enc
        elif typ == 'set':
            child = build_data(val, tags, S)
            buf += struct.pack('<i', len(child))
            buf += child
        elif typ in ('float',):
            buf += struct.pack('<f', val)
        elif typ in ('bool', 'int'):
            buf += struct.pack('<i', val)
        elif typ == 'long2':
            buf += struct.pack('<ii', val[0], val[1])
        elif typ == 'guid':
            buf += val
        elif typ == 'raw':
            buf += val
    return bytes(buf)


def build_spb(headers, tags, data_section):
    buf = bytearray()
    buf += struct.pack('<H', MAGIC)
    for h in headers:
        buf += struct.pack('<i', h)
    for g, f in tags:
        buf += g
        buf += struct.pack('<i', f)
    buf += data_section
    return bytes(buf)


def patch(tree, patches):
    out = []
    for ti, typ, val in tree:
        if ti in patches:
            out.append((ti, typ, patches[ti]))
        elif typ == 'set':
            out.append((ti, 'set', patch(val, patches)))
        else:
            out.append((ti, typ, val))
    return out


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    S = parse_textdecode_cs(os.path.join(base, 'TextDecode.Data.cs'))
    K = build_K_table(S)
    print(f"TextDecode: {sum(1 for x in S if x)} chars, roundtrip OK")
    for t in ["Hello", "InGamePanels", "html_UI/x.html"]:
        assert text_decode(K, text_encode(S, t)) == t

    for name, path in [
        ("VSR", "vs-radio-toolbar/InGamePanels/vs-radio-toolbar.spb"),
        ("Navigraph", "navigraph-ingamepanels-charts/InGamePanels/navigraph-ingamepanels-charts.spb"),
    ]:
        fp = os.path.join(base, path)
        if not os.path.exists(fp):
            continue
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        data = read_spb(fp)
        headers, tags, ds = parse_header(data)
        tree, ep = walk(data, ds, len(data), tags, K)
        tail = data[ep:]
        if tail:
            print(f"TRAILING({len(tail)}B): {tail.hex()}")
            tree.append((-1, 'tail', tail))

        rebuilt = build_spb(headers, tags, build_data(tree, tags, S))
        match = "✓" if rebuilt == data else f"✗ (orig={len(data)} rebuilt={len(rebuilt)})"
        print(f"Roundtrip: {match}")
        if rebuilt != data:
            for i in range(min(len(data), len(rebuilt))):
                if data[i] != rebuilt[i]:
                    print(f"  First diff @0x{i:04X}")
                    break


if __name__ == '__main__':
    main()
