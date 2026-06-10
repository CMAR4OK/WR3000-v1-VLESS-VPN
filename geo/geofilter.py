import sys

def read_varint(b, i):
    shift = 0; result = 0
    while True:
        byte = b[i]; i += 1
        result |= (byte & 0x7f) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, i

def parse_entries(data):
    i = 0; n = len(data); entries = []
    while i < n:
        tag, i = read_varint(data, i)
        field = tag >> 3; wt = tag & 7
        if wt == 2:
            length, i = read_varint(data, i)
            payload = data[i:i+length]; i += length
            if field == 1:
                entries.append(payload)
        elif wt == 0:
            _, i = read_varint(data, i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            raise Exception("bad wiretype %d at top" % wt)
    return entries

def country_code(entry):
    i = 0; n = len(entry)
    while i < n:
        tag, i = read_varint(entry, i)
        field = tag >> 3; wt = tag & 7
        if wt == 2:
            length, i = read_varint(entry, i)
            val = entry[i:i+length]; i += length
            if field == 1:
                return val.decode('utf-8', 'replace')
        elif wt == 0:
            _, i = read_varint(entry, i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break
    return None

def encode_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7f; v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b); break
    return bytes(out)

def build(entries):
    out = bytearray()
    for e in entries:
        out += b'\x0a' + encode_varint(len(e)) + e
    return bytes(out)

mode = sys.argv[1]
data = open(sys.argv[2], 'rb').read()
entries = parse_entries(data)
if mode == 'list':
    cats = sorted(set((country_code(e) or '?') for e in entries))
    print(len(entries), "entries,", len(cats), "categories")
    print(",".join(cats))
else:
    keep = set(x.upper() for x in sys.argv[4].split(","))
    kept = [e for e in entries if (country_code(e) or "").upper() in keep]
    open(sys.argv[3], "wb").write(build(kept))
    got = sorted((country_code(e) or "?") for e in kept)
    missing = keep - set(g.upper() for g in got)
    print("kept", len(kept), "of", len(entries), "->", sys.argv[3])
    print("categories:", ",".join(got))
    if missing:
        print("MISSING:", ",".join(sorted(missing)))
