#!/usr/bin/env python3
"""Extract case-relevant geometry from the upstream TK44 KiCad PCB.

Usage: extract_kicad.py <path/to/Ladniy/TK44> > reference/tk44-pcb.json

Reads pcb/TK44/TK44.kicad_pcb (outline, mount holes, components) and
case/fr-4-bottom/bottom.kicad_pcb (cutouts of the original FR-4 bottom,
used to place battery / JST pockets). Coordinates stay in KiCad space
(mm, y grows downwards); tk44_case.py converts them.
"""
import json, math, re, sys


def parse(s):
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', s)
    st = [[]]
    for t in toks:
        if t == "(":
            st.append([])
        elif t == ")":
            x = st.pop()
            st[-1].append(x)
        else:
            st[-1].append(t[1:-1] if t.startswith('"') else t)
    return st[0][0]


def find(n, k):
    return [c for c in n if isinstance(c, list) and c and c[0] == k]


def one(n, k):
    r = find(n, k)
    return r[0] if r else None


def pt(n):
    return [float(n[1]), float(n[2])]


def edge_items(pcb):
    for k in ("gr_line", "gr_arc", "gr_circle"):
        for g in find(pcb, k):
            if one(g, "layer")[1] == "Edge.Cuts":
                yield g


def loops(pcb):
    """Group Edge.Cuts lines/arcs into ordered closed loops."""
    segs = []
    for g in edge_items(pcb):
        if g[0] == "gr_circle":
            continue
        s = {"start": pt(one(g, "start")), "end": pt(one(g, "end"))}
        if g[0] == "gr_arc":
            s["mid"] = pt(one(g, "mid"))
        segs.append(s)

    def close(a, b):
        return math.dist(a, b) < 0.01

    out = []
    left = segs[:]
    while left:
        loop = [left.pop(0)]
        while not close(loop[-1]["end"], loop[0]["start"]):
            tail = loop[-1]["end"]
            for i, s in enumerate(left):
                if close(s["start"], tail):
                    loop.append(left.pop(i))
                    break
                if close(s["end"], tail):  # reversed segment
                    s = left.pop(i)
                    s["start"], s["end"] = s["end"], s["start"]
                    loop.append(s)
                    break
            else:
                raise SystemExit("open outline loop at %s" % tail)
        out.append(loop)
    return out


def bbox(loop):
    xs = [p[0] for s in loop for p in (s["start"], s["end"])]
    ys = [p[1] for s in loop for p in (s["start"], s["end"])]
    return [min(xs), min(ys), max(xs), max(ys)]


def main(root):
    pcb = parse(open(f"{root}/pcb/TK44/TK44.kicad_pcb").read())
    bottom = parse(open(f"{root}/case/fr-4-bottom/bottom.kicad_pcb").read())

    pl = sorted(loops(pcb), key=lambda l: -len(l))
    outline = pl[0]
    pb = bbox(outline)

    holes, parts = [], {}
    for f in find(pcb, "footprint"):
        lib = f[1].split(":")[1]
        at = one(f, "at")
        pos = [float(at[1]), float(at[2])]
        rot = float(at[3]) if len(at) > 3 else 0.0
        ref = next(p[2] for p in find(f, "fp_text") if p[1] == "reference")
        side = "bottom" if one(f, "layer")[1] == "B.Cu" else "top"
        if lib.startswith("Hole_Mount"):
            holes.append({"ref": ref, "at": pos})
        elif lib.startswith("Switch_Mx"):
            parts.setdefault("switches", []).append({"ref": ref, "at": pos, "rot": rot})
        elif lib in ("USB-C-C168688", "MSK-12C02", "K2-1187SQ",
                     "Battery_Connector", "Holyiot-18010-nRF52840"):
            parts[lib] = {"ref": ref, "at": pos, "rot": rot, "side": side}

    # The FR-4 bottom shares the PCB outline, offset; align it by bbox.
    bl = sorted(loops(bottom), key=lambda l: -len(l))
    bb = bbox(bl[0])
    dx, dy = pb[0] - bb[0], pb[1] - bb[1]
    cutouts = []
    for l in bl[1:]:
        x0, y0, x1, y1 = bbox(l)
        cutouts.append([x0 + dx, y0 + dy, x1 + dx, y1 + dy])

    json.dump({
        "source": "https://github.com/Ladniy/TK44 (CERN-OHL-P v2.0)",
        "units": "mm, KiCad coordinates (y down)",
        "pcb_thickness": 1.6,
        "bbox": pb,
        "outline": outline,
        "inner_slots": [bbox(l) for l in pl[1:]],
        "mount_holes": sorted(holes, key=lambda h: h["ref"]),
        "parts": parts,
        "fr4_bottom_cutouts": cutouts,
    }, sys.stdout, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
