"""Read the bot IDs from the official packed Cap'n Proto replay header.

Replay's map, botA and botB are pointer fields 0, 1 and 2. No game events are
decoded. Based on the Replay schema in the official unswbc 1.2.2/1.2.3 viewers.
"""
import gzip
import struct


def bot_ids(payload):
    if payload.startswith(b"\x1f\x8b"):
        payload = gzip.decompress(payload)
    data, i = bytearray(), 0
    while i < len(payload):
        tag = payload[i]
        i += 1
        word = bytearray(8)
        for bit in range(8):
            if tag & (1 << bit):
                word[bit] = payload[i]
                i += 1
        data.extend(word)
        if tag in (0, 255):
            count = payload[i] * 8
            i += 1
            if tag == 0:
                data.extend(bytes(count))
            else:
                data.extend(payload[i:i + count])
                i += count
    count = struct.unpack_from("<I", data)[0] + 1
    if not 1 <= count <= 512:
        raise ValueError("Invalid replay segment count")
    sizes = struct.unpack_from(f"<{count}I", data, 4)
    offset = ((count + 2) // 2) * 8
    segments = []
    for size in sizes:
        segments.append(memoryview(data)[offset:offset + size * 8])
        offset += size * 8

    def word(segment, position):
        return struct.unpack_from("<Q", segments[segment], position * 8)[0]

    def resolve(segment, position):
        value = word(segment, position)
        if value & 3 == 2:
            landing, target = (value >> 3) & 0x1fffffff, value >> 32
            if value & 4:
                far, tag = word(target, landing), word(target, landing + 1)
                return tag, far >> 32, (far >> 3) & 0x1fffffff
            return resolve(target, landing)
        displacement = (value >> 2) & 0x3fffffff
        if displacement & 0x20000000:
            displacement -= 0x40000000
        return value, segment, position + 1 + displacement

    root, segment, start = resolve(0, 0)
    if root & 3 != 0 or (root >> 48) < 3:
        raise ValueError("Replay header does not contain bot IDs")
    pointers = start + ((root >> 32) & 0xffff)

    def text(field):
        pointer, target, start = resolve(segment, pointers + field)
        if pointer == 0:
            return ""
        if pointer & 3 != 1 or (pointer >> 32) & 7 != 2:
            raise ValueError("Replay bot ID is not a text field")
        length = pointer >> 35
        raw = bytes(segments[target][start * 8:start * 8 + length])
        if not raw.endswith(b"\0"):
            raise ValueError("Invalid replay bot ID")
        return raw[:-1].decode("utf-8")

    return text(1), text(2)
