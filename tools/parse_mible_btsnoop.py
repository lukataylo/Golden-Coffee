#!/usr/bin/env python3
"""Decode a Mi Home BLE pairing capture (btsnoop_hci.log) down to the ATT writes
and notifications, so we can reverse the HOTO lamp's "mible" secure-auth.

Why: the lamp (hoto.light.lamp) uses Xiaomi's newer BLE secure-auth — its GET_INFO
doesn't return the 20-byte device-id the public miauth `register` flow expects, and
the cloud beaconkey is all-FF (no token `login`). The only way to learn the real
handshake is to watch the official Mi Home app do it. See docs/xiaomi-ble-hcisnoop.md
for how to record the capture; then:

    python tools/parse_mible_btsnoop.py btsnoop_hci.log

It prints, in order, every GATT write / notification with direction, the
characteristic UUID (resolved from the capture's service discovery), and the bytes —
flagging the Xiaomi auth service (fe95: control 0x10, data 0x16/0x17/0x18) and the
miot.im control service (0101/0102). Compare that transcript against what
.tools/mible_register.py does to find where our flow diverges.

Pure-Python: parses the btsnoop container + HCI-ACL + L2CAP + ATT directly, no
tshark/scapy needed. Handles H4 (datalink 1002) and unencapsulated HCI (1001/1000).
"""
from __future__ import annotations

import struct
import sys

# ATT opcodes we care about.
ATT = {
    0x0A: "ReadReq", 0x0B: "ReadResp",
    0x08: "ReadByTypeReq", 0x09: "ReadByTypeResp",
    0x04: "FindInfoReq", 0x05: "FindInfoResp",
    0x12: "WriteReq", 0x13: "WriteResp", 0x52: "WriteCmd",
    0x1B: "Notify", 0x1D: "Indicate", 0x1E: "Confirm",
}
WRITES = {0x12, 0x52}
RECVS = {0x1B, 0x1D, 0x0B}

# Annotate known Xiaomi characteristics by UUID suffix/short form.
FE95 = {  # 16-bit chars under service fe95 (the secure-auth service)
    "0010": "AUTH/UPNP control-point", "0016": "AUTH data (this lamp's AVDTP)",
    "0017": "AUTH 0x17", "0018": "AUTH 0x18", "001a": "AUTH 0x1a",
    "0004": "fw-version", "0005": "AUTH 0x05",
}
MIOT = {  # miot.im control service 00000100-0065-6c62-2e74-6f696d2e696d
    "00000101": "miot.im WRITE (commands)", "00000102": "miot.im NOTIFY (replies)",
}


def short_uuid(u: str) -> str:
    """Render a UUID compactly + a human label if we recognise it."""
    u = u.lower()
    base = "-0000-1000-8000-00805f9b34fb"
    if u.endswith(base):
        s16 = u[4:8]
        return f"0x{s16} ({FE95.get(s16, '?')})" if s16 in FE95 else f"0x{s16}"
    head = u[:8]
    if head in MIOT:
        return f"{head}… ({MIOT[head]})"
    return u


def parse_btsnoop(path: str):
    """Yield (is_recv, hci_payload) for each ACL record in a btsnoop file."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"btsnoop\x00":
        raise SystemExit("not a btsnoop file (bad magic)")
    _ver, datalink = struct.unpack(">II", data[8:16])
    h4 = datalink == 1002  # H4: each packet prefixed with an HCI type byte
    off = 16
    while off + 24 <= len(data):
        orig_len, incl_len, flags, _drops, _ts = struct.unpack(">IIIIq", data[off:off + 24])
        off += 24
        pkt = data[off:off + incl_len]
        off += incl_len
        if len(pkt) < incl_len:
            break
        is_recv = bool(flags & 0x01)
        is_cmd_evt = bool(flags & 0x02)
        if is_cmd_evt:
            continue  # HCI command/event, not ACL data
        if h4:
            if not pkt or pkt[0] != 0x02:  # only HCI ACL (0x02)
                continue
            pkt = pkt[1:]
        yield is_recv, pkt


def reassemble_l2cap(records):
    """ACL → L2CAP reassembly per connection handle, yielding (is_recv, att_pdu)."""
    buffers: dict[int, dict] = {}
    for is_recv, acl in records:
        if len(acl) < 4:
            continue
        handle_flags, acl_len = struct.unpack("<HH", acl[:4])
        handle = handle_flags & 0x0FFF
        pb = (handle_flags >> 12) & 0x3  # 0b10 first, 0b01 continuation
        payload = acl[4:4 + acl_len]
        if pb == 0x1 and handle in buffers:  # continuation fragment
            b = buffers[handle]
            b["data"] += payload
        else:  # start of a new L2CAP PDU
            if len(payload) < 4:
                continue
            l2_len, cid = struct.unpack("<HH", payload[:4])
            buffers[handle] = {"need": l2_len, "cid": cid, "data": payload[4:], "recv": is_recv}
        b = buffers.get(handle)
        if b and len(b["data"]) >= b["need"]:
            if b["cid"] == 0x0004:  # ATT
                yield b["recv"], b["data"][:b["need"]]
            del buffers[handle]


def main(path: str):
    records = list(parse_btsnoop(path))
    handle_uuid: dict[int, str] = {}
    events = []  # (is_recv, opcode, handle, value)

    for is_recv, att in reassemble_l2cap(records):
        if not att:
            continue
        op = att[0]
        # Learn value-handle → UUID from characteristic-declaration reads (type 0x2803).
        if op == 0x09 and len(att) >= 2:  # ReadByTypeResp
            elen = att[1]
            body = att[2:]
            for i in range(0, len(body) - elen + 1, elen):
                el = body[i:i + elen]
                if elen in (7, 21) and len(el) == elen:
                    vhandle = struct.unpack("<H", el[3:5])[0]
                    uuid_b = el[5:]
                    if len(uuid_b) == 2:
                        u = f"0000{uuid_b[::-1].hex()}-0000-1000-8000-00805f9b34fb"
                    else:
                        u = _fmt128(uuid_b)
                    handle_uuid[vhandle] = u
        if op in (0x12, 0x52, 0x1B, 0x1D, 0x0A, 0x0B) and len(att) >= 3:
            handle = struct.unpack("<H", att[1:3])[0]
            value = att[3:]
            events.append((is_recv, op, handle, value))

    print(f"# {path}: {len(records)} ACL records, {len(handle_uuid)} chars discovered, "
          f"{len(events)} ATT ops\n")
    for is_recv, op, handle, value in events:
        if op in (0x0A,):  # skip bare read requests (no value)
            continue
        arrow = "<-" if (is_recv or op in RECVS) else "->"
        uuid = handle_uuid.get(handle)
        label = short_uuid(uuid) if uuid else f"handle 0x{handle:04x}"
        print(f"{arrow} {ATT.get(op, hex(op)):9} {label:42} {value.hex(' ')}")


def _fmt128(b: bytes) -> str:
    h = b[::-1].hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python tools/parse_mible_btsnoop.py <btsnoop_hci.log>")
        raise SystemExit(2)
    main(sys.argv[1])
