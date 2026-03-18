#!/usr/bin/env python3
"""
Decode and encode MSFS SimPropBinary (.spb) InGamePanel definition files.

Based on the format documented in the spb2xml project (leppie/spb2xml)
and reverse-engineered from working MSFS InGamePanel .spb files.
"""

import struct
import sys
import uuid

MAGIC = 0xEBAC


def read_uint16(f):
    return struct.unpack('<H', f.read(2))[0]

def read_int32(f):
    return struct.unpack('<i', f.read(4))[0]

def read_uint32(f):
    return struct.unpack('<I', f.read(4))[0]

def read_float(f):
    return struct.unpack('<f', f.read(4))[0]

def read_guid(f):
    data = f.read(16)
    return uuid.UUID(bytes_le=data)

def read_bytes(f, n):
    return f.read(n)


def decode_spb(filepath):
    """Decode an .spb file and return its structure."""
    with open(filepath, 'rb') as f:
        # Read magic
        magic = read_uint16(f)
        assert magic == MAGIC, f"Bad magic: 0x{magic:04X}"

        # Read 12 header int32s
        headers = [read_int32(f) for _ in range(12)]
        ntags = headers[6]
        print(f"Magic: 0x{magic:04X}")
        print(f"Headers: {headers}")
        print(f"ntags: {ntags}")
        print(f"Header ends at offset: 0x{f.tell():04X}")

        # Read tag definitions (ntags - 1 entries)
        tags = []
        for i in range(ntags - 1):
            g = read_guid(f)
            flag = read_int32(f)
            tags.append((g, flag))
            print(f"  Tag[{i}]: GUID={g}  flag={flag} (0x{flag & 0xFFFFFFFF:08X})")

        print(f"Tag data ends at offset: 0x{f.tell():04X}")
        print()

        # Read data section
        file_size = f.seek(0, 2)
        f.seek(2 + 12*4 + (ntags-1)*20)  # back to data start

        depth = 0
        while f.tell() < file_size:
            pos = f.tell()
            tag_number = read_int32(f)
            if tag_number == 0:
                print(f"  {'  '*depth}[0x{pos:04X}] tag_number=0 (null/end)")
                continue

            tag_idx = tag_number - 1
            if tag_idx < 0 or tag_idx >= len(tags):
                print(f"  {'  '*depth}[0x{pos:04X}] INVALID tag_number={tag_number}")
                break

            tag_guid = tags[tag_idx][0]
            tag_flag = tags[tag_idx][1]

            # Peek at next 4 bytes to help identify type
            next_pos = f.tell()
            peek = f.read(4) if f.tell() + 4 <= file_size else b''
            f.seek(next_pos)

            peek_int = struct.unpack('<i', peek)[0] if len(peek) == 4 else 0
            peek_uint = struct.unpack('<I', peek)[0] if len(peek) == 4 else 0
            peek_float = struct.unpack('<f', peek)[0] if len(peek) == 4 else 0

            # If flag is 0xFFFFFFFF (-1), it's typically a set (container)
            # If flag is 0x00000004, it's typically a property
            # If flag is 0x00000008, it's typically a text property

            if tag_flag == -1:
                # SetDef - read size
                set_size = read_int32(f)
                end_pos = f.tell() + set_size
                print(f"  {'  '*depth}[0x{pos:04X}] SET tag[{tag_idx}] GUID={tag_guid} size={set_size} (data 0x{f.tell():04X}-0x{end_pos:04X})")
                depth += 1
            elif tag_flag == 8:
                # TEXT property - read length then string
                str_len = read_int32(f)
                if str_len > 0:
                    str_bytes = f.read(str_len)
                    try:
                        text = str_bytes.decode('utf-8').rstrip('\x00')
                    except:
                        text = str_bytes.hex()
                else:
                    text = ""
                print(f"  {'  '*depth}[0x{pos:04X}] TEXT tag[{tag_idx}] GUID={tag_guid} = \"{text}\"")
            elif tag_flag == 4:
                # Could be FLOAT, BOOL, ULONG, LONG, or ENUM
                val = read_int32(f)
                fval = struct.unpack('<f', struct.pack('<i', val))[0]
                # Heuristic: if the float value looks reasonable, show both
                print(f"  {'  '*depth}[0x{pos:04X}] PROP tag[{tag_idx}] GUID={tag_guid} = int:{val} float:{fval:.3f}")
            elif tag_flag == 0x10:
                # GUID property
                guid_val = read_guid(f)
                print(f"  {'  '*depth}[0x{pos:04X}] GUID tag[{tag_idx}] GUID={tag_guid} = {guid_val}")
            else:
                # Unknown - try reading as int32
                val = read_int32(f)
                print(f"  {'  '*depth}[0x{pos:04X}] UNK(flag=0x{tag_flag & 0xFFFFFFFF:08X}) tag[{tag_idx}] GUID={tag_guid} = {val}")

        print(f"\nFile size: {file_size} bytes, ended at: 0x{f.tell():04X}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 spb_tool.py <file.spb>")
        sys.exit(1)

    decode_spb(sys.argv[1])
