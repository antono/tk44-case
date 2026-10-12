"""TK44 3D-printed tray case + wrist rests (FreeCAD script).

Replaces the original FR-4 bottom of the Ladniy/TK44 sandwich with a printed
tray. The FR-4 plate and the PCB stay: the plate is screwed to the tray floor
through the 8 stock M2x8 standoffs (they pass through the 4.4 mm PCB holes).

Run headless (exports STEP/STL into out/, saves tk44-case.FCStd):
    freecad -c tk44_case.py          # or: nix run
or inside a running FreeCAD (Python console / MCP), builds the document only:
    p = "<repo>/tk44_case.py"
    exec(open(p).read(), {"__file__": p, "__name__": "tk44_case"})

Geometry comes from reference/tk44-pcb.json (tools/extract_kicad.py).
FreeCAD coordinates: origin = PCB bbox centre, +Y = away from the user
(KiCad y is flipped), Z = 0 at the tray underside.
"""
import json
import math
import os

import FreeCAD as App
import Part
from FreeCAD import Vector as V

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:  # exec() without __file__: assume the repo is the cwd
    HERE = os.getcwd()

# --- parameters (mm) --------------------------------------------------------
P = dict(
    # stack-up
    floor=4.0,            # tray floor thickness (replaces 1.6 mm FR-4 bottom)
    standoff=8.0,         # stock M2 standoff length, floor top -> plate bottom
    plate_t=1.6,          # FR-4 switch plate
    pcb_t=1.6,
    plate_to_pcb=5.0,     # MX: plate top -> PCB top
    # walls
    gap=0.5,              # PCB/plate edge -> inner wall
    wall=2.5,
    wall_above_plate=0.0, # wall top relative to plate top
    # screws (M2 from below into the standoffs)
    screw_d=2.4,          # clearance hole
    screw_len=6.0,        # M2x6 from below (M2x5 would engage only 1.6 mm)
    screw_head_d=4.4,     # counterbore for a 4.0 mm flat head
    screw_head_t=0.5,
    screw_head_clear=0.1,
    screw_engage_min=2.0, # thread inside the standoff, >= 1 x d
    plate_screw_len=5.0,  # stock M2x5 from the top through the plate
    layer_h=0.2,          # print layer height: counterbore + bridge layers
    bridge_layers=2,      # layers per bridge stage (slot, then square)
    # rubber bumpers (glued into recesses on the underside)
    bumper_d=10.5,        # 10 mm bumpers + clearance
    bumper_depth=1.0,
    # pockets in the floor top (from the original FR-4 bottom cut-outs)
    battery_pocket_depth=2.5,  # 3.0 gap + 2.5 = 5.5 mm for a 502035 cell
    jst_pocket_depth=3.4,
    # back wall openings
    usb_slot_w=14.0,
    usb_top_below_plate=4.0,  # measured: plate top -> top of the USB-C port
    usb_port_h=3.2,           # USB-C receptacle shell height
    usb_slot_h=7.5,           # opening height, centred on the port (plug overmold)
    switch_slot_w=10.0,
    reset_slot_w=10.0,
    slot_bridge=1.6,      # wall kept above switch/reset slots (plate thickness)
    # wrist rest attachment: vertical dovetail on the front wall of each half
    dovetail=False,       # disabled for now: rests stand free next to the tray
    dt_base_w=9.0,
    dt_tip_w=13.0,
    dt_depth=5.0,         # protrusion from the outer wall
    dt_h=10.0,
    dt_clear=0.25,
    # wrist rests
    rest_w=95.0,          # along the front edge of the half
    rest_d=80.0,          # towards the user
    rest_h=20.0,          # top surface above the desk, without bumpers
    rest_gap=0.5,         # rest <-> tray clearance
    rest_corner_r=8.0,
    rest_top_fillet=4.0,
    # vase-mode fit test: a solid whose single printed wall has its INNER
    # surface on the tray cavity (board outline + gap)
    vase_line_w=0.45,     # slicer outer-wall line width in spiral vase mode
    vase_bottom=0.6,      # solid bottom under the cavity (0 -> open ring)
    vase_bump=3.0,        # outward pockets for USB / switch / reset
)

# shallowest counterbore that hides the head, rounded up to whole layers;
# above it two sacrificial-bridge layers (slot, then square) let the slicer
# bridge the counterbore ceiling with straight lines instead of circling it
SCREW_CB = round(math.ceil((P["screw_head_t"] + P["screw_head_clear"]) / P["layer_h"] - 1e-9)
                 * P["layer_h"], 6)
SCREW_ENGAGE = P["screw_len"] - (P["floor"] - SCREW_CB)
assert SCREW_ENGAGE >= P["screw_engage_min"], "screw too short: %.1f mm in the standoff" % SCREW_ENGAGE
assert SCREW_CB + P["screw_len"] < P["floor"] + P["standoff"] + P["plate_t"] - P["plate_screw_len"], \
    "bottom and plate screws collide inside the standoff"

# derived Z levels
FLOOR_TOP = P["floor"]
PLATE_BOT = FLOOR_TOP + P["standoff"]
PLATE_TOP = PLATE_BOT + P["plate_t"]
PCB_TOP = PLATE_TOP - P["plate_to_pcb"]
PCB_BOT = PCB_TOP - P["pcb_t"]
WALL_TOP = PLATE_TOP + P["wall_above_plate"]

# bumper centres, KiCad coords, left half; mirrored for the right half
TRAY_BUMPERS_L = [(72.0, 146.0), (88.0, 168.0), (128.0, 119.0), (185.0, 198.5)]

REF = json.load(open(os.path.join(HERE, "reference", "tk44-pcb.json")))
X0 = (REF["bbox"][0] + REF["bbox"][2]) / 2
Y0 = (REF["bbox"][1] + REF["bbox"][3]) / 2


def k2v(p, z=0.0):
    """KiCad (x, y) -> FreeCAD vector."""
    return V(p[0] - X0, Y0 - p[1], z)


def kmirror(p):
    return (2 * X0 - p[0], p[1])


# --- 2D helpers -------------------------------------------------------------
def outline_face():
    edges = []
    segs = REF["outline"]
    for i, s in enumerate(segs):
        # KiCad endpoints differ by ~1e-6; snap to shared vertices
        a, b = k2v(segs[i - 1]["end"]), k2v(s["end"])
        if "mid" in s:
            edges.append(Part.Arc(a, k2v(s["mid"]), b).toShape())
        else:
            edges.append(Part.LineSegment(a, b).toShape())
    w = Part.Wire(edges)  # extract_kicad.py already orders the loop
    assert w.isClosed(), "PCB outline is not closed"
    f = Part.Face(w)
    if f.Area < 0:
        f.reverse()
    return f


def rect_face(x0, y0, x1, y1):
    pts = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    return Part.Face(Part.makePolygon(pts + pts[:1]))


def kbox(x0, y0, x1, y1):
    a, b = k2v((x0, y0)), k2v((x1, y1))
    return rect_face(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))


def offset(face, d):
    return face.makeOffset2D(d, join=0)  # arc joins -> rounded corners


def prism(face, z0, h):
    return face.translated(V(0, 0, z0)).extrude(V(0, 0, h))


def cyl(center, d, z0, h):
    return Part.makeCylinder(d / 2, h, V(center.x, center.y, z0))


def poly_face(pts):
    pts = [V(p.x, p.y, 0) for p in pts]
    return Part.Face(Part.makePolygon(pts + pts[:1]))


# --- board footprint --------------------------------------------------------
def board_face():
    """PCB outline with the USB notch at the back filled in."""
    f = outline_face()
    usb = REF["parts"]["USB-C-C168688"]["at"]
    notch = kbox(usb[0] - 5, REF["bbox"][1] + 3.0, usb[0] + 5, usb[1] + 4)
    solid = prism(f, 0, 1).fuse(prism(notch, 0, 1)).removeSplitter()
    return max((x for x in solid.Faces if x.BoundBox.ZMax < 1e-6), key=lambda x: x.Area)


def front_edge_frame(mirror=False):
    """Frame on the straight front edge of the left (or right) half.

    Returns (origin, u, n): origin on the outer tray wall at the pinky end,
    u along the edge towards the thumbs, n outwards (towards the user).
    """
    # longest outline segment whose both ends lie on the front-left area
    best = None
    for s in REF["outline"]:
        if "mid" in s:
            continue
        a, b = s["start"], s["end"]
        if max(a[0], b[0]) > X0 - 40 or min(a[1], b[1]) < Y0:
            continue
        L = math.dist(a, b)
        if best is None or L > best[0]:
            best = (L, a, b)
    _, a, b = best
    if a[0] > b[0]:
        a, b = b, a
    if mirror:
        a, b = kmirror(a), kmirror(b)
    A, B = k2v(a), k2v(b)
    u = (B - A).normalize()
    n = V(u.y, -u.x, 0)
    if n.y > 0:
        n = -n
    out = P["gap"] + P["wall"]
    return A + n * out, u, n


def dovetail_face(origin, u, n, s, back=0.5):
    """Trapezoid: narrow at the wall (t=0), wide at t=dt_depth."""
    c = origin + u * s
    hb = P["dt_base_w"] / 2
    ht = P["dt_tip_w"] / 2
    t1 = P["dt_depth"]
    # straight part behind the wall plane so the tab fuses into the wall
    pts = [c - n * back - u * hb, c - u * hb, c + n * t1 - u * ht,
           c + n * t1 + u * ht, c + u * hb, c - n * back + u * hb]
    return poly_face(pts)


# --- tray -------------------------------------------------------------------
def make_tray():
    bf = board_face()
    inner = offset(bf, P["gap"])
    outer = offset(bf, P["gap"] + P["wall"])

    tray = prism(outer, 0, WALL_TOP)
    tray = tray.cut(prism(inner, FLOOR_TOP, WALL_TOP))

    # dovetail tabs for the wrist rests (mid of the straight front edge)
    for m in ((False, True) if P["dovetail"] else ()):
        o, u, n = front_edge_frame(m)
        s = dovetail_station(m)
        tray = tray.fuse(prism(dovetail_face(o, u, n, s, back=P["wall"]), 0, P["dt_h"]))

    cuts = []
    # M2 screws + counterbores from below
    for h in REF["mount_holes"]:
        c = k2v(h["at"])
        bh, d, D = P["layer_h"] * P["bridge_layers"], P["screw_d"], P["screw_head_d"]
        cuts.append(cyl(c, D, -1, SCREW_CB + 1))
        # bridge stage 1: slot across the counterbore, stage 2: square
        cuts.append(prism(rect_face(c.x - D / 2, c.y - d / 2, c.x + D / 2, c.y + d / 2), SCREW_CB, bh))
        cuts.append(prism(rect_face(c.x - d / 2, c.y - d / 2, c.x + d / 2, c.y + d / 2), SCREW_CB + bh, bh))
        cuts.append(cyl(c, d, SCREW_CB + 2 * bh, P["floor"]))

    # pockets taken from the original FR-4 bottom cut-outs
    cut_b = REF["fr4_bottom_cutouts"]
    battery = max(cut_b, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    jst_at = REF["parts"]["Battery_Connector"]["at"]
    jst = min(cut_b, key=lambda r: math.dist(((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), jst_at))
    for r, d in ((battery, P["battery_pocket_depth"]), (jst, P["jst_pocket_depth"])):
        cuts.append(prism(kbox(*r), FLOOR_TOP - d, d + 1))

    # back wall openings: USB-C, power switch and reset button (on this board
    # revision it sits on the back edge, mirrored to the switch around the
    # USB port). Each keeps a bridge at plate level.
    back_y = outer.BoundBox.YMax
    slot_top = WALL_TOP - P["slot_bridge"]
    usb_z = PLATE_TOP - P["usb_top_below_plate"] - P["usb_port_h"] / 2
    usb_z0 = max(FLOOR_TOP, usb_z - P["usb_slot_h"] / 2)
    usb_z1 = min(slot_top, usb_z + P["usb_slot_h"] / 2)
    (usb_x, usb_w), (switch_x, switch_w), (reset_x, reset_w) = back_slots()
    for x, w, z0, z1 in ((usb_x, usb_w, usb_z0, usb_z1),
                         (switch_x, switch_w, FLOOR_TOP, slot_top),
                         (reset_x, reset_w, FLOOR_TOP, slot_top)):
        f = rect_face(x - w / 2, back_y - P["gap"] - P["wall"] - 3, x + w / 2, back_y + 1)
        cuts.append(prism(f, z0, z1 - z0))

    # bumper recesses
    for p in bumper_points(TRAY_BUMPERS_L, inner):
        cuts.append(cyl(p, P["bumper_d"], -1, P["bumper_depth"] + 1))

    tray = tray.cut(Part.makeCompound(cuts)).removeSplitter()
    return tray


def bumper_points(left_pts, face):
    pts = [k2v(p) for p in left_pts] + [k2v(kmirror(p)) for p in left_pts]
    area = math.pi * (P["bumper_d"] / 2 + 1.0) ** 2
    for p in pts:
        c = Part.Face(Part.Wire(Part.makeCircle(P["bumper_d"] / 2 + 1.0, p)))
        if abs(face.common(c).Area - area) > 0.5:
            raise ValueError("bumper at %s leaves the floor" % p)
    return pts


def dovetail_station(mirror=False):
    """Distance along u (from the frame origin) of the dovetail centre."""
    # centre of the straight front segment
    o, u, n = front_edge_frame(mirror)
    bf = board_face()
    # straight segment length = projection extent of outline points on the edge line
    L = 0
    for s in REF["outline"]:
        if "mid" in s:
            continue
        for p in (s["start"], s["end"]):
            q = k2v(kmirror(p) if mirror else p)
            t = (q - o).dot(n)
            if abs(t + P["gap"] + P["wall"]) < 0.05:
                L = max(L, (q - o).dot(u))
    return L / 2


# --- wrist rests ------------------------------------------------------------
def front_keepout(mirror=False):
    """Polygon of the tray's front contour (one half) grown by the rest gap.

    Built from the straight front outline segments offset outwards and
    intersected pairwise: a clean polygon without the tiny corner arcs of
    makeOffset2D, which break fillets on the rest.
    """
    bf = board_face()
    d = P["gap"] + P["wall"] + P["rest_gap"]
    segs = []
    for s in REF["outline"]:
        if "mid" in s or math.dist(s["start"], s["end"]) < 3:
            continue
        a, b = s["start"], s["end"]
        if (a[0] + b[0]) / 2 >= X0 or max(a[1], b[1]) < Y0 + 10:
            continue
        if mirror:
            a, b = kmirror(a), kmirror(b)
        segs.append([k2v(a), k2v(b)])
    segs.sort(key=lambda s: abs((s[0] + s[1]).x / 2))  # outer -> centre
    # orient along the chain and offset outwards
    lines = []
    for i, (a, b) in enumerate(segs):
        if i + 1 < len(segs):
            nxt = segs[i + 1]
            if min((a - p).Length for p in nxt) < min((b - p).Length for p in nxt):
                a, b = b, a
        elif (a - lines[-1][1]).Length > (b - lines[-1][1]).Length:
            a, b = b, a
        dvec = (b - a).normalize()
        nrm = V(-dvec.y, dvec.x, 0)
        mid = (a + b) * 0.5
        if bf.isInside(mid + nrm * 0.1, 1e-6, True):
            nrm = -nrm
        lines.append((a + nrm * d, b + nrm * d))

    def cross(l1, l2):
        p, r = l1[0], l1[1] - l1[0]
        q, s = l2[0], l2[1] - l2[0]
        t = ((q - p).x * s.y - (q - p).y * s.x) / (r.x * s.y - r.y * s.x)
        return p + r * t

    far = 200.0
    a0, b0 = lines[0]
    an, bn = lines[-1]
    pts = [a0 - (b0 - a0).normalize() * far]
    pts += [cross(lines[i], lines[i + 1]) for i in range(len(lines) - 1)]
    pts.append(bn + (bn - an).normalize() * far)
    pts += [V(pts[-1].x, far, 0), V(pts[0].x, far, 0)]
    return poly_face(pts)


def make_rest(mirror=False):
    o, u, n = front_edge_frame(mirror)
    s0 = -P["gap"] - P["wall"]
    r = P["rest_corner_r"]
    # rounded rectangle: shrink by r, offset back out with arc joins
    s1, s2, t1, t2 = s0 + r, s0 + P["rest_w"] - r, r, P["rest_d"] - r
    f = offset(poly_face([o + u * s1 + n * t1, o + u * s2 + n * t1,
                          o + u * s2 + n * t2, o + u * s1 + n * t2]), r)
    f = max(f.cut(front_keepout(mirror)).Faces, key=lambda x: x.Area)

    rest = prism(f, 0, P["rest_h"])
    if P["rest_top_fillet"] > 0:
        top = [e for e in rest.Edges
               if abs(e.BoundBox.ZMin - P["rest_h"]) < 1e-6 and abs(e.BoundBox.ZMax - P["rest_h"]) < 1e-6]
        try:
            filleted = rest.makeFillet(P["rest_top_fillet"], top)
            if filleted.isValid():
                rest = filleted
            else:
                App.Console.PrintWarning("rest fillet invalid, keeping sharp top\n")
        except Part.OCCError:
            App.Console.PrintWarning("rest fillet failed, keeping sharp top\n")

    cuts = []
    if P["dovetail"]:
        s = dovetail_station(mirror)
        # uniform clearance normal to every flank of the tab
        cuts.append(prism(offset(dovetail_face(o, u, n, s, back=2), P["dt_clear"]), -1,
                          P["dt_h"] + 2 * P["dt_clear"] + 1))
    # bumpers: corners inset, keep those fully inside
    inset = P["bumper_d"] / 2 + 6
    for a, b in ((0.12, 0.2), (0.88, 0.2), (0.15, 0.85), (0.85, 0.85)):
        p = o + u * (s0 + P["rest_w"] * a) + n * (P["rest_d"] * b)
        circ = Part.Face(Part.Wire(Part.makeCircle(inset, p)))
        if abs(f.common(circ).Area - circ.Area) < 0.5:
            cuts.append(cyl(p, P["bumper_d"], -1, P["bumper_depth"] + 1))
    return rest.cut(Part.makeCompound(cuts)).removeSplitter()


# --- vase-mode fit test -----------------------------------------------------
def back_edge_y(face, x):
    """Y of the face's back edge at the given X."""
    cut = Part.LineSegment(V(x, -500, 0), V(x, 500, 0)).toShape().common(face)
    return cut.BoundBox.YMax


def back_slots():
    """(x, width) of the back-wall openings: USB-C, power switch, reset."""
    usb_x = k2v(REF["parts"]["USB-C-C168688"]["at"]).x
    switch_x = k2v(REF["parts"]["MSK-12C02"]["at"]).x
    return ((usb_x, P["usb_slot_w"]), (switch_x, P["switch_slot_w"]),
            (2 * usb_x - switch_x, P["reset_slot_w"]))


def make_vase_fit():
    """Solid for spiral-vase printing: one wall around the keyboard.

    The slicer lays the single perimeter inside the model outline, so the
    outline is the cavity grown by one line width; the printed wall's inner
    face then sits where the tray's inner wall is. Openings in the wall are
    impossible in vase mode, so USB / switch / reset get outward pockets.
    """
    bf = board_face()
    cav = offset(bf, P["gap"])
    pockets = []
    for x, w in back_slots():
        y = back_edge_y(bf, x)
        pockets.append(prism(rect_face(x - w / 2, y - 1, x + w / 2,
                                       y + P["gap"] + P["vase_bump"]), 0, 1))
    solid = prism(cav, 0, 1).fuse(pockets).removeSplitter()
    cav = max((f for f in solid.Faces if f.BoundBox.ZMax < 1e-6), key=lambda f: f.Area)
    z0 = FLOOR_TOP - P["vase_bottom"]
    return prism(offset(cav, P["vase_line_w"]), z0, WALL_TOP - z0)


# --- reference ghosts -------------------------------------------------------
def make_ghosts():
    bf = outline_face()
    pcb = prism(bf, PCB_BOT, P["pcb_t"])
    plate = prism(bf, PLATE_BOT, P["plate_t"])
    sw = []
    for s in REF["parts"]["switches"]:
        c = k2v(s["at"], PLATE_TOP)
        b = Part.makeBox(15.6, 15.6, 6.6, V(-7.8, -7.8, 0))
        b.rotate(V(0, 0, 0), V(0, 0, 1), -s["rot"])
        sw.append(b.translated(c))
    return pcb, plate, Part.makeCompound(sw)


# --- build ------------------------------------------------------------------
def build(doc_name="TK44_Case"):
    if doc_name in App.listDocuments():
        App.closeDocument(doc_name)
    doc = App.newDocument(doc_name)
    tray = make_tray()
    rl, rr = make_rest(False), make_rest(True)
    objs = {}
    for name, shp in (("Tray", tray), ("WristRestL", rl), ("WristRestR", rr),
                      ("TrayVaseFit", make_vase_fit())):
        objs[name] = doc.addObject("Part::Feature", name)
        objs[name].Shape = shp
    pcb, plate, sw = make_ghosts()
    for name, shp in (("ref_PCB", pcb), ("ref_Plate", plate), ("ref_Switches", sw)):
        objs[name] = doc.addObject("Part::Feature", name)
        objs[name].Shape = shp
    doc.recompute()
    if App.GuiUp:
        import FreeCADGui as Gui
        colors = {"Tray": (0.25, 0.25, 0.3), "WristRestL": (0.55, 0.45, 0.35),
                  "WristRestR": (0.55, 0.45, 0.35), "ref_PCB": (0.1, 0.5, 0.2),
                  "ref_Plate": (0.8, 0.7, 0.2), "ref_Switches": (0.9, 0.9, 0.9),
                  "TrayVaseFit": (0.3, 0.5, 0.8)}
        for name, o in objs.items():
            vo = o.ViewObject
            vo.ShapeColor = colors[name]
            if name.startswith("ref_"):
                vo.Transparency = 60
            if name == "TrayVaseFit":
                vo.Visibility = False
        Gui.SendMsgToActiveView("ViewFit")
        Gui.activeDocument().activeView().viewIsometric()
    return doc


def export(doc, out_dir=os.path.join(HERE, "out")):
    import Mesh
    import MeshPart
    os.makedirs(out_dir, exist_ok=True)
    doc.saveAs(os.path.join(HERE, "tk44-case.FCStd"))  # tracked source
    for name, fn in (("Tray", "tk44-tray"), ("WristRestL", "tk44-wristrest-left"),
                     ("WristRestR", "tk44-wristrest-right"),
                     ("TrayVaseFit", "tk44-tray-vase-fit")):
        shp = doc.getObject(name).Shape
        shp.exportStep(os.path.join(out_dir, fn + ".step"))
        m = MeshPart.meshFromShape(Shape=shp, LinearDeflection=0.05,
                                   AngularDeflection=0.2, Relative=False)
        m.write(os.path.join(out_dir, fn + ".stl"))
    App.Console.PrintMessage("exported to %s\n" % out_dir)


DOC = build()
if not App.GuiUp:
    export(DOC)
