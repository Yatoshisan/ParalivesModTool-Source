#!/usr/bin/env python3
"""
Paralives Mod Tool  v2.0 by N0R0IK0
Requires:  pip install customtkinter pillow

v2.0 changes vs v1.1:
  - Full mesh rebuild (any vertex count, reads bone weights from FBX)
  - Bone names auto-read from existing .import — nothing hardcoded
  - Writes both .import AND .import.custom on every apply
  - FBX→Unity winding fix (v1↔v2 swap) so RecalculateNormals() works correctly
  - Organised backup system: ParalivesBackupFiles/<asset>/<timestamp>/
  - Binary-safe metacache update (handles BOM + CRLF)
  - One-click restore of latest backup
  - Live mode-detection badge (Same Topology / Full Rebuild)
"""

import os, re, sys, json, struct, zlib, hashlib, math, shutil, threading, datetime
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
except ImportError:
    import tkinter.messagebox as _mb
    _mb.showerror("Missing dependency",
                  "Please run:\n\n  pip install customtkinter\n\nthen restart.")
    sys.exit(1)

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ── Palette ───────────────────────────────────────────────────────────────────────
BG        = "#0d0d0d"
SURF      = "#161616"
SURF2     = "#1e1e1e"
SURF3     = "#272727"
BORDER    = "#2e2e2e"
TXT       = "#f0f0f0"
TXT_DIM   = "#5a5a5a"
WBTN      = "#ececec"
WBTN_TXT  = "#0d0d0d"
WBTN_HOV  = "#d0d0d0"
SBTN      = "#252525"
SBTN_HOV  = "#333333"
DIVIDER   = "#2a2a2a"
BADGE_A   = "#1a2a1a"   # same-topology badge bg
BADGE_A_T = "#6ee27a"   # same-topology badge text
BADGE_B   = "#1a1a2a"   # full-rebuild badge bg
BADGE_B_T = "#7ab4e2"   # full-rebuild badge text

# ── Backup root: <script_folder>/../ParalivesBackupFiles ──────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.normpath(os.path.join(_HERE, "..", "ParalivesBackupFiles"))


# ═══════════════════════════════════════════════════════════════════════════════════
#  BACKUP SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════════

def _backup_slot(asset_path):
    name = os.path.basename(asset_path)
    ts   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(BACKUP_ROOT, name, ts)

def create_backup(asset_path, mod_folder, log):
    """Copy asset + all sidecars into a timestamped backup folder."""
    bdir = _backup_slot(asset_path)
    os.makedirs(bdir, exist_ok=True)

    candidates = [
        asset_path,
        asset_path + ".import",
        asset_path + ".import.custom",
        asset_path + ".meta",
    ]
    saved = []
    for src in candidates:
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(bdir, os.path.basename(src)))
            saved.append(os.path.basename(src))

    # Also back up the relevant metacache
    try:
        mc = find_metacache_for(mod_folder, asset_path)
        shutil.copy2(mc, os.path.join(bdir, os.path.basename(mc)))
        saved.append(os.path.basename(mc))
    except Exception:
        pass

    log(f"  Backup → {bdir}")
    log(f"  Files:    {', '.join(saved)}")
    return bdir

def latest_backup_dir(asset_path):
    """Return the most recent backup directory for this asset, or None."""
    folder = os.path.join(BACKUP_ROOT, os.path.basename(asset_path))
    if not os.path.isdir(folder):
        return None
    entries = sorted(os.listdir(folder), reverse=True)
    for e in entries:
        p = os.path.join(folder, e)
        if os.path.isdir(p):
            return p
    return None


# ═══════════════════════════════════════════════════════════════════════════════════
#  META / CHECKSUM HELPERS
# ═══════════════════════════════════════════════════════════════════════════════════

def sha1_of(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest().upper()

def sha1_bytes(data):
    return hashlib.sha1(data).hexdigest().upper()

def read_meta_value(meta_path, key):
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(key + ":"):
                return line.strip().split(":", 1)[1]
    return None

def update_meta_checksum(meta_path, new_cs):
    with open(meta_path, "r", encoding="utf-8") as f:
        txt = f.read()
    txt = re.sub(r"ImportFileCheckSum:[0-9A-Fa-f]+",
                 f"ImportFileCheckSum:{new_cs}", txt)
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(txt)

def find_metacache_for(mod_folder, asset_path):
    """
    Locate the .Metacache responsible for this asset.
    Paralives stores them in <mod_folder>/_Metacache/ named after
    the asset's directory path with path separators replaced by semicolons.
    e.g.  Species/Human/BodyParts  →  Species;Human;BodyParts.Metacache
    """
    rel_dir   = os.path.relpath(os.path.dirname(asset_path), mod_folder)
    cache_key = rel_dir.replace(os.sep, ";").replace("/", ";")
    cache_dir = os.path.join(mod_folder, "_Metacache")

    primary = os.path.join(cache_dir, cache_key + ".Metacache")
    if os.path.exists(primary):
        return primary

    if os.path.isdir(cache_dir):
        for fn in os.listdir(cache_dir):
            if fn.lower().endswith(".metacache"):
                return os.path.join(cache_dir, fn)

    for fn in os.listdir(mod_folder):
        if fn.lower().endswith(".metacache"):
            return os.path.join(mod_folder, fn)

    raise FileNotFoundError(
        f"No .Metacache file found.\nExpected:\n{primary}")

def update_metacache_checksum(cache_path, asset_path, mod_folder, new_cs):
    """Binary-safe replacement of ImportFileCheckSum for a specific asset."""
    rel = os.path.relpath(asset_path, mod_folder).replace("\\", "/")
    with open(cache_path, "rb") as f:
        raw = f.read()

    idx = raw.find(rel.encode("utf-8"))
    if idx >= 0:
        cs_off = raw.find(b"ImportFileCheckSum:", idx)
        if 0 < cs_off - idx < 500:
            end = cs_off + len(b"ImportFileCheckSum:")
            while end < len(raw) and raw[end:end+1] not in (b"\r", b"\n", b"\x00"):
                end += 1
            raw = (raw[:cs_off] +
                   b"ImportFileCheckSum:" + new_cs.encode("ascii") +
                   raw[end:])
            with open(cache_path, "wb") as f:
                f.write(raw)
            return

    # Fallback: replace first occurrence anywhere in file
    raw = re.sub(rb"ImportFileCheckSum:[0-9A-Fa-f]+",
                 b"ImportFileCheckSum:" + new_cs.encode("ascii"), raw, count=1)
    with open(cache_path, "wb") as f:
        f.write(raw)


# ═══════════════════════════════════════════════════════════════════════════════════
#  IMPORT BINARY PARSER
# ═══════════════════════════════════════════════════════════════════════════════════

def parse_import_info(data):
    """
    Parse the header of a .import (or .import.custom) binary.

    Binary layout:
      int32  V         vertex count
      V×12   float32   positions (x,y,z)
      int32  I         index count
      I×4    int32     triangle indices
      int32  Nv        normal count (= V)
      Nv×12  float32   normals
      int32  UV1c      UV1 count
      UV1c×8 float32   UV1 (u,v)
      int32  UV2c      UV2 count
      UV2c×8 float32   UV2
      int32  Cc        vertex color count (usually 0)
      Cc×12  float32   vertex colors
      int32  BWc       bone weight count (= V)
      BWc×32 bytes     bone weights: 4×int32 index + 4×float32 weight
      int32  B         bone name count
      UTF-8            bone names joined by \\n
    """
    off = 0
    V   = struct.unpack_from("<i", data, off)[0]; off += 4
    off += V * 12
    I   = struct.unpack_from("<i", data, off)[0]; off += 4
    idx_off = off;                                 off += I * 4
    Nv  = struct.unpack_from("<i", data, off)[0]; off += 4
    nrm_off = off;                                 off += Nv * 12
    UV1c = struct.unpack_from("<i", data, off)[0]; off += 4
    uv1_off = off;                                  off += UV1c * 8
    UV2c = struct.unpack_from("<i", data, off)[0]; off += 4
    off += UV2c * 8
    Cc   = struct.unpack_from("<i", data, off)[0]; off += 4
    off += Cc * 12
    BWc  = struct.unpack_from("<i", data, off)[0]; off += 4
    bw_off = off;                                   off += BWc * 32
    B    = struct.unpack_from("<i", data, off)[0]; off += 4

    raw_names = data[off:off + max(B * 80, 256)]
    bone_names = raw_names.decode("utf-8", errors="replace").split("\n")[:B]
    bone_names = [n.strip("\x00 \r") for n in bone_names]

    return {
        "V": V, "I": I, "Nv": Nv, "UV1c": UV1c, "UV2c": UV2c, "Cc": Cc, "BWc": BWc,
        "idx_off": idx_off, "nrm_off": nrm_off,
        "uv1_off": uv1_off, "bw_off": bw_off,
        "bone_names": bone_names,
    }


# ═══════════════════════════════════════════════════════════════════════════════════
#  FBX BINARY READER
# ═══════════════════════════════════════════════════════════════════════════════════

def _fbx_node(data, off):
    if off + 13 > len(data): return None, off
    end = struct.unpack_from("<I", data, off)[0]
    if end == 0: return None, off + 13
    pl   = struct.unpack_from("<I", data, off + 8)[0]
    nl   = data[off + 12]
    name = data[off + 13:off + 13 + nl].decode("ascii", errors="replace")
    return {"name": name, "end": end, "ps": off + 13 + nl, "pl": pl}, end

def _fbx_arr(data, off):
    tc = chr(data[off]); off += 1
    cnt, enc, cl = struct.unpack_from("<III", data, off); off += 12
    raw = data[off:off + cl]
    if enc == 1: raw = zlib.decompress(raw)
    fmt = {"d": "d", "f": "f", "i": "i", "l": "q", "b": "b"}.get(tc, "i")
    return list(struct.unpack_from(f"<{cnt}{fmt}", raw))

def _fbx_props(data, ps, pend):
    vals = []; off = ps
    while off < pend:
        tc = chr(data[off]); off += 1
        if   tc == "Y": vals.append(struct.unpack_from("<h", data, off)[0]); off += 2
        elif tc == "C": vals.append(bool(data[off]));                         off += 1
        elif tc == "I": vals.append(struct.unpack_from("<i", data, off)[0]); off += 4
        elif tc == "F": vals.append(struct.unpack_from("<f", data, off)[0]); off += 4
        elif tc == "D": vals.append(struct.unpack_from("<d", data, off)[0]); off += 8
        elif tc == "L": vals.append(struct.unpack_from("<q", data, off)[0]); off += 8
        elif tc in ("S", "R"):
            n = struct.unpack_from("<I", data, off)[0]; off += 4
            vals.append(data[off:off + n]); off += n
        elif tc in ("f", "d", "i", "l", "b"):
            cnt, enc, cl = struct.unpack_from("<III", data, off); off += 12
            raw = data[off:off + cl]
            if enc == 1: raw = zlib.decompress(raw)
            fmt = {"f":"f","d":"d","i":"i","l":"q","b":"b"}[tc]
            vals.append(list(struct.unpack_from(f"<{cnt}{fmt}", raw)))
            off += cl
        else:
            break
    return vals

def _fbx_str(b):
    if isinstance(b, (bytes, bytearray)):
        return b.split(b"\x00")[0].decode("utf-8", "replace")
    return str(b)

def _walk(data, node):
    off = node["ps"] + node["pl"]
    while off < node["end"]:
        ch, _ = _fbx_node(data, off)
        if ch is None: off += 13; continue
        yield ch
        off = ch["end"]

def read_fbx_geometry(path):
    """Read positions, polygon indices and UVs from an FBX binary file."""
    with open(path, "rb") as f:
        data = f.read()
    res = {"positions": [], "poly_indices": None, "tri_indices": [],
           "uv_raw": None, "uv_index": None,
           "uv_mapping": "ByPolygonVertex", "uv_reference": "IndexToDirect",
           "uv_per_vertex": None}
    off = 27
    while off < len(data):
        node, noff = _fbx_node(data, off)
        if node is None: break
        if node["name"] == "Objects":
            for ch in _walk(data, node):
                if ch["name"] != "Geometry": continue
                pos = poly = uv_v = uv_i = None
                um = "ByPolygonVertex"; ur = "IndexToDirect"
                for gc in _walk(data, ch):
                    if gc["name"] == "Vertices":
                        raw = _fbx_arr(data, gc["ps"])
                        pos = [(raw[i], raw[i+1], raw[i+2]) for i in range(0, len(raw), 3)]
                    elif gc["name"] == "PolygonVertexIndex":
                        poly = _fbx_arr(data, gc["ps"])
                    elif gc["name"] == "LayerElementUV":
                        for uc in _walk(data, gc):
                            if uc["name"] == "UV":
                                raw = _fbx_arr(data, uc["ps"])
                                uv_v = [(raw[i], raw[i+1]) for i in range(0, len(raw), 2)]
                            elif uc["name"] == "UVIndex":
                                uv_i = _fbx_arr(data, uc["ps"])
                            elif uc["name"] == "MappingInformationType":
                                p = _fbx_props(data, uc["ps"], uc["ps"] + uc["pl"])
                                if p: um = _fbx_str(p[0])
                            elif uc["name"] == "ReferenceInformationType":
                                p = _fbx_props(data, uc["ps"], uc["ps"] + uc["pl"])
                                if p: ur = _fbx_str(p[0])
                if pos is None: continue
                res["positions"]  = pos
                res["poly_indices"] = poly
                res["uv_raw"] = uv_v; res["uv_index"] = uv_i
                res["uv_mapping"] = um; res["uv_reference"] = ur
                if poly:
                    tris = []; face = []
                    for v in poly:
                        face.append(v if v >= 0 else -(v+1))
                        if v < 0:
                            for k in range(1, len(face)-1):
                                tris.append([face[0], face[k], face[k+1]])
                            face = []
                    res["tri_indices"] = tris
                break
        off = noff
    return res

def _quick_fbx_vert_count(path):
    """Fast read — returns FBX vertex count without full parse."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        off = 27
        while off < len(data):
            node, noff = _fbx_node(data, off)
            if node is None: break
            if node["name"] == "Objects":
                for ch in _walk(data, node):
                    if ch["name"] != "Geometry": continue
                    for gc in _walk(data, ch):
                        if gc["name"] == "Vertices":
                            return len(_fbx_arr(data, gc["ps"])) // 3
            off = noff
    except Exception:
        pass
    return 0

def read_fbx_bone_weights(path, n_verts, bone_name_to_idx):
    """
    Read per-vertex bone weights from FBX skin clusters.
    Returns list of [(bone_idx, weight) × 4] per vertex.
    bone_name_to_idx: dict mapping bone name → index (from existing .import).
    """
    with open(path, "rb") as f:
        data = f.read()

    geom_nodes = {}; skin_nodes = set(); cluster_data = {}; connections = []
    off = 27
    while off < len(data):
        node, noff = _fbx_node(data, off)
        if node is None: break
        if node["name"] == "Objects":
            for ch in _walk(data, node):
                props = _fbx_props(data, ch["ps"], ch["ps"] + ch["pl"])
                if not props: continue
                nid = props[0] if isinstance(props[0], int) else None
                if nid is None: continue
                if ch["name"] == "Geometry":
                    for gc in _walk(data, ch):
                        if gc["name"] == "Vertices":
                            geom_nodes[nid] = len(_fbx_arr(data, gc["ps"])) // 3
                            break
                elif ch["name"] == "Deformer":
                    sp = [_fbx_str(p) for p in props if isinstance(p, (bytes, bytearray))]
                    if len(sp) < 2: continue
                    if sp[1] == "Skin":
                        skin_nodes.add(nid)
                    elif sp[1] == "Cluster":
                        vi = wt = None
                        for sc in _walk(data, ch):
                            if sc["name"] == "Indexes":  vi = _fbx_arr(data, sc["ps"])
                            elif sc["name"] == "Weights": wt = _fbx_arr(data, sc["ps"])
                        if vi is not None and wt is not None:
                            cluster_data[nid] = (sp[0], vi, wt)
        elif node["name"] == "Connections":
            for ch in _walk(data, node):
                if ch["name"] != "C": continue
                cp = _fbx_props(data, ch["ps"], ch["ps"] + ch["pl"])
                if len(cp) >= 3 and _fbx_str(cp[0]) == "OO":
                    connections.append((cp[1], cp[2]))
        off = noff

    c2p = {c: p for c, p in connections}
    p2c = {}
    for c, p in connections:
        p2c.setdefault(p, []).append(c)

    target = next((gid for gid, vc in geom_nodes.items() if vc == n_verts), None)
    if target is None and geom_nodes:
        target = next(iter(geom_nodes))

    skin = next((sid for sid in skin_nodes if c2p.get(sid) == target), None)
    if skin is not None:
        clusters = [cluster_data[cid] for cid in p2c.get(skin, []) if cid in cluster_data]
    else:
        clusters = list(cluster_data.values())

    wt_table = [{} for _ in range(n_verts)]
    for bone_label, idxs, wts in clusters:
        bi = bone_name_to_idx.get(bone_label, -1)
        if bi < 0: continue
        for vi, wt in zip(idxs, wts):
            if 0 <= vi < n_verts:
                wt_table[vi][bi] = wt

    result = []
    for d in wt_table:
        items = sorted(d.items(), key=lambda x: -x[1])[:4]
        s = sum(w for _, w in items)
        if s > 0: items = [(bi, w/s) for bi, w in items]
        while len(items) < 4: items.append((0, 0.0))
        result.append(items)
    return result


# ═══════════════════════════════════════════════════════════════════════════════════
#  IMPORT BINARY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════════

def _iter_faces(poly_idx):
    face = []; start = 0
    for i, v in enumerate(poly_idx):
        face.append(v if v >= 0 else -(v+1))
        if v < 0:
            yield start, face; start = i+1; face = []

def build_import_vertices(geo):
    """
    Expand FBX polygon data into unique import vertices (position + UV pairs).
    CRITICAL: swaps v1↔v2 in every triangle to counteract the FBX X-flip
    (right-handed → left-handed), ensuring RecalculateNormals() produces
    outward-facing normals at runtime.
    """
    positions = geo["positions"]
    poly_idx  = geo["poly_indices"] or []
    uv_raw    = geo["uv_raw"]
    uv_index  = geo["uv_index"]
    uv_perv   = geo["uv_per_vertex"]

    poly_verts = [v if v >= 0 else -(v+1) for v in poly_idx]
    if uv_perv:
        pv_uv = [uv_perv[v] for v in poly_verts]
    elif uv_raw and uv_index:
        pv_uv = [uv_raw[uv_index[i]] for i in range(len(poly_verts))]
    else:
        pv_uv = [(0.0, 0.0)] * len(poly_verts)

    unique_map = {}; imp_pos = []; imp_uv = []; pv_to_imp = []
    for pvi, (fv, uv) in enumerate(zip(poly_verts, pv_uv)):
        key = (fv, (round(uv[0], 5), round(uv[1], 5)))
        if key not in unique_map:
            unique_map[key] = len(imp_pos)
            imp_pos.append(positions[fv])
            imp_uv.append(uv)
        pv_to_imp.append(unique_map[key])

    imp_tris = []; pvi = 0
    for _, face in _iter_faces(poly_idx):
        n = len(face); base = pvi
        for k in range(1, n-1):
            imp_tris.append([pv_to_imp[base],
                              pv_to_imp[base+k+1],   # v1↔v2 swap: restores CCW after X-flip
                              pv_to_imp[base+k]])
        pvi += n

    imp_to_fbx = [-1] * len(imp_pos)
    for (fv, _), iv in unique_map.items():
        imp_to_fbx[iv] = fv

    return imp_pos, imp_uv, imp_tris, imp_to_fbx

def build_import_binary(positions_fbx, uvs, tri_indices, bone_weights_4, bone_names):
    """
    Build a complete .import binary from import-space data.
    tri_indices must already be CCW-wound (v1↔v2 swap applied by build_import_vertices).
    bone_names: list of bone name strings, in index order.
    """
    N = len(positions_fbx)
    flat = [v for tri in tri_indices for v in tri]
    I    = len(flat)
    f32  = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]

    # FBX right-handed → Unity left-handed: negate X
    imp_pos = [(f32(-x), f32(y), f32(z)) for x, y, z in positions_fbx]

    # Area-weighted smooth normals (standard CCW cross product — winding already correct)
    nacc = [(0.0, 0.0, 0.0)] * N
    for tri in tri_indices:
        i0, i1, i2 = tri
        v0, v1, v2 = imp_pos[i0], imp_pos[i1], imp_pos[i2]
        fn = _cross(_sub(v1, v0), _sub(v2, v0))
        nacc[i0] = _add(nacc[i0], fn)
        nacc[i1] = _add(nacc[i1], fn)
        nacc[i2] = _add(nacc[i2], fn)
    normals = [_norm(n) for n in nacc]

    buf = bytearray()
    buf += struct.pack("<i", N)
    for x, y, z in imp_pos:    buf += struct.pack("<fff", x, y, z)      # positions
    buf += struct.pack("<i", I)
    for v in flat:              buf += struct.pack("<i",  v)              # indices
    buf += struct.pack("<i", N)
    for nx, ny, nz in normals:  buf += struct.pack("<fff", nx, ny, nz)   # normals
    buf += struct.pack("<i", N)
    for u, v in uvs:            buf += struct.pack("<ff", f32(u), f32(v)) # UV1
    buf += struct.pack("<i", N)
    for u, v in uvs:            buf += struct.pack("<ff", f32(u), f32(v)) # UV2 = UV1
    buf += struct.pack("<i", 0)                                            # 0 vertex colors
    buf += struct.pack("<i", N)
    for bw in bone_weights_4:
        buf += struct.pack("<4i", *[bi for bi, _ in bw])
        buf += struct.pack("<4f", *[w  for _,  w in bw])
    buf += struct.pack("<i", len(bone_names))
    buf += "\n".join(bone_names).encode("utf-8")
    return bytes(buf)


# ── Math helpers ──────────────────────────────────────────────────────────────────
def _f32(v): return struct.unpack("<f", struct.pack("<f", v))[0]
def _norm(v):
    l = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
    return (v[0]/l, v[1]/l, v[2]/l) if l > 1e-10 else (0., 1., 0.)
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _sub(a,  b):  return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _add(a,  b):  return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


# ═══════════════════════════════════════════════════════════════════════════════════
#  MESH OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════════════

def _map_cache_path(mod_folder, new_fbx_path):
    tag  = hashlib.md5(new_fbx_path.encode()).hexdigest()[:8]
    name = os.path.splitext(os.path.basename(new_fbx_path))[0]
    return os.path.join(mod_folder, ".modtool", f"{name}_{tag}.json")

def _same_topology_patch(orig_data, info, new_fbx_path, mod_folder, log):
    """
    Patch positions + normals only; preserve UV, bone weights, bone names.
    Original triangle indices are already correctly wound — no winding swap needed.
    """
    V       = info["V"]
    idx_off = info["idx_off"]
    nrm_off = info["nrm_off"]
    I       = info["I"]
    T       = I // 3

    orig_pos = [struct.unpack_from("<fff", orig_data, 4 + i*12) for i in range(V)]
    indices  = list(struct.unpack_from(f"<{I}I", orig_data, idx_off))

    geo     = read_fbx_geometry(new_fbx_path)
    new_fbx = geo["positions"]
    log(f"  FBX: {len(new_fbx)} verts  |  Import: {V} verts")
    if not new_fbx:
        raise ValueError("No vertices found in FBX.")

    map_path = _map_cache_path(mod_folder, new_fbx_path)
    os.makedirs(os.path.dirname(map_path), exist_ok=True)

    if os.path.exists(map_path):
        log("  Loading cached vertex mapping...")
        with open(map_path) as f: i2f = json.load(f)
    else:
        log("  Building vertex mapping (may take a moment)...")
        nf32 = [(_f32(x), _f32(y), _f32(z)) for x, y, z in new_fbx]
        i2f  = [-1] * V
        for ii, (ix, iy, iz) in enumerate(orig_pos):
            bd, bj = 0.08, -1
            for j, (fx, fy, fz) in enumerate(nf32):
                d = abs(-fx-ix) + abs(fy-iy) + abs(fz-iz)
                if d < bd: bd, bj = d, j
            i2f[ii] = bj
        with open(map_path, "w") as f: json.dump(i2f, f)
        log("  Mapping cached.")

    matched = sum(1 for j in i2f if j >= 0)
    log(f"  Matched: {matched}/{V} vertices")
    if matched < V * 0.5:
        raise ValueError(
            f"Vertex matching failed: only {matched}/{V} ({matched*100//V}%) matched.\n"
            "Make sure you exported the SAME mesh (same vertices, just moved/shaped).")

    new_pos = []
    for ii in range(V):
        j = i2f[ii]
        if 0 <= j < len(new_fbx):
            fx, fy, fz = new_fbx[j]
            new_pos.append((_f32(-fx), _f32(fy), _f32(fz)))
        else:
            new_pos.append(orig_pos[ii])

    buf = bytearray(orig_data)
    for i, (x, y, z) in enumerate(new_pos):
        struct.pack_into("<fff", buf, 4 + i*12, x, y, z)

    nacc = [(0., 0., 0.)] * V
    for t in range(T):
        i0, i1, i2 = indices[t*3], indices[t*3+1], indices[t*3+2]
        fn = _cross(_sub(new_pos[i1], new_pos[i0]), _sub(new_pos[i2], new_pos[i0]))
        nacc[i0] = _add(nacc[i0], fn)
        nacc[i1] = _add(nacc[i1], fn)
        nacc[i2] = _add(nacc[i2], fn)
    for i, n in enumerate(nacc):
        nx, ny, nz = _norm(n)
        struct.pack_into("<fff", buf, nrm_off + i*12, nx, ny, nz)

    return bytes(buf)


def _full_rebuild(geo, new_fbx_path, bone_names, log):
    """Full binary rebuild from FBX geometry. Reads bone weights from FBX."""
    n_fbx        = len(geo["positions"])
    b_name_to_idx = {name: i for i, name in enumerate(bone_names)}

    log("  Building import vertices (winding fix applied)...")
    imp_pos, imp_uv, imp_tris, imp_to_fbx = build_import_vertices(geo)
    N = len(imp_pos)
    log(f"  Import vertices: {N}  |  Triangles: {len(imp_tris)}")

    log("  Reading bone weights from FBX...")
    fbx_bw = read_fbx_bone_weights(new_fbx_path, n_fbx, b_name_to_idx)

    import_bw = []
    for iv in range(N):
        fv = imp_to_fbx[iv]
        import_bw.append(fbx_bw[fv] if 0 <= fv < len(fbx_bw)
                         else [(0, 1.0), (0, 0.0), (0, 0.0), (0, 0.0)])

    bw_ok = sum(1 for bw in import_bw if any(w > 0.01 for _, w in bw))
    log(f"  Vertices with bone weights: {bw_ok}/{N}")
    if bw_ok < N * 0.5:
        log("  WARNING: <50% of vertices have bone weights.")
        log("  Make sure the FBX was exported with Armature + skin weights.")

    log("  Assembling binary...")
    return build_import_binary(imp_pos, imp_uv, imp_tris, import_bw, bone_names)


def apply_mesh(fbx_path, new_fbx_path, mod_folder, log):
    """
    Apply mesh replacement.
    • Auto-detects same topology vs full rebuild.
    • Creates backup before any changes.
    • Writes .import AND .import.custom with identical content.
    • Updates .meta and _Metacache checksums.
    """
    imp_path    = fbx_path + ".import"
    custom_path = fbx_path + ".import.custom"
    meta_path   = fbx_path + ".meta"

    if not os.path.exists(imp_path):
        raise FileNotFoundError(f"No .import file found:\n{imp_path}")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"No .meta file found:\n{meta_path}")

    with open(imp_path, "rb") as f:
        orig_data = f.read()
    info       = parse_import_info(orig_data)
    bone_names = info["bone_names"]
    V_orig     = info["V"]
    bn_preview = ", ".join(bone_names[:3]) + ("…" if len(bone_names) > 3 else "")
    log(f"  Import: {V_orig} verts | Bones: {bn_preview}")

    log("Creating backup...")
    create_backup(fbx_path, mod_folder, log)

    log(f"Reading new FBX: {os.path.basename(new_fbx_path)}")
    new_geo = read_fbx_geometry(new_fbx_path)
    n_fbx   = len(new_geo["positions"])
    log(f"  FBX vertices: {n_fbx}")
    if n_fbx == 0:
        raise ValueError("No vertices found in the FBX — check the file and export settings.")

    ratio = n_fbx / max(V_orig, 1)
    if 0.85 <= ratio <= 1.15:
        log("Mode: Same Topology")
        out_data = _same_topology_patch(orig_data, info, new_fbx_path, mod_folder, log)
    else:
        log(f"Mode: Full Rebuild  (FBX {n_fbx} vs import {V_orig})")
        out_data = _full_rebuild(new_geo, new_fbx_path, bone_names, log)

    with open(imp_path, "wb") as f:    f.write(out_data)
    log(f"  Written: {os.path.basename(imp_path)}")
    with open(custom_path, "wb") as f: f.write(out_data)
    log(f"  Written: {os.path.basename(custom_path)}")

    new_cs = sha1_bytes(out_data)
    update_meta_checksum(meta_path, new_cs)
    log("  .meta updated")
    try:
        mc = find_metacache_for(mod_folder, fbx_path)
        update_metacache_checksum(mc, fbx_path, mod_folder, new_cs)
        log(f"  Metacache updated  ({new_cs[:16]}…)")
    except Exception as e:
        log(f"  Warning (metacache): {e}")

    log("Done — launch Paralives to test.")


def restore_latest_mesh_backup(fbx_path, mod_folder, log):
    """Restore .import, .import.custom and .meta from the most recent backup."""
    bdir = latest_backup_dir(fbx_path)
    if not bdir:
        raise FileNotFoundError(
            f"No backup found for:\n{os.path.basename(fbx_path)}\n\n"
            f"Backups live in:\n{os.path.join(BACKUP_ROOT, os.path.basename(fbx_path))}")

    log(f"Restoring from:\n  {bdir}")
    asset_dir = os.path.dirname(fbx_path)
    restored  = []

    for fn in os.listdir(bdir):
        src = os.path.join(bdir, fn)
        if fn.lower().endswith(".metacache"):
            try:
                mc = find_metacache_for(mod_folder, fbx_path)
                shutil.copy2(src, mc)
                restored.append(fn)
            except Exception:
                pass
        else:
            dst = os.path.join(asset_dir, fn)
            shutil.copy2(src, dst)
            restored.append(fn)

    if not restored:
        raise ValueError("Nothing was restored — backup folder may be empty.")
    log(f"  Restored: {', '.join(restored)}")
    log("Done — launch Paralives to test.")


# ═══════════════════════════════════════════════════════════════════════════════════
#  TEXTURE OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════════════

def _write_png_imports(png_path, img, log):
    w, h = img.size
    for suffix, factor in [("", 1.0), ("5", 0.5), ("25", 0.25), ("125", 0.125)]:
        nw  = max(1, int(w * factor)); nh = max(1, int(h * factor))
        out = img.resize((nw, nh), PILImage.LANCZOS) if factor != 1.0 else img.copy()
        out = out.transpose(PILImage.FLIP_TOP_BOTTOM)
        ext = f".{suffix}.import" if suffix else ".import"
        out.save(png_path + ext, "PNG")
        log(f"  Wrote {os.path.basename(png_path) + ext}")

def apply_transparent(png_path, mod_folder, log):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed — run:  pip install Pillow")
    meta = png_path + ".meta"
    log("Creating backup...")
    create_backup(png_path, mod_folder, log)
    ow = read_meta_value(meta, "OriginalWidth")
    oh = read_meta_value(meta, "OriginalHeight")
    if ow and oh:
        w, h = int(ow), int(oh)
    else:
        tmp = PILImage.open(png_path); w, h = tmp.size; tmp.close()
    log(f"Creating transparent {w}×{h} image...")
    img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
    img.save(png_path, "PNG")
    _write_png_imports(png_path, img, log)
    cs = sha1_of(png_path)
    update_meta_checksum(meta, cs)
    try:
        mc = find_metacache_for(mod_folder, png_path)
        update_metacache_checksum(mc, png_path, mod_folder, cs)
    except Exception as e:
        log(f"  Warning (metacache): {e}")
    log("  Checksum updated.")
    log("Done — launch Paralives to test.")

def apply_custom_texture(png_path, custom_png, mod_folder, log):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed — run:  pip install Pillow")
    meta = png_path + ".meta"
    log("Creating backup...")
    create_backup(png_path, mod_folder, log)
    log(f"Loading: {os.path.basename(custom_png)}")
    img = PILImage.open(custom_png).convert("RGBA")
    log(f"  Size: {img.size[0]}×{img.size[1]}")
    img.save(png_path, "PNG")
    _write_png_imports(png_path, img, log)
    img.close()
    cs = sha1_of(png_path)
    update_meta_checksum(meta, cs)
    try:
        mc = find_metacache_for(mod_folder, png_path)
        update_metacache_checksum(mc, png_path, mod_folder, cs)
    except Exception as e:
        log(f"  Warning (metacache): {e}")
    log("  Checksum updated.")
    log("Done — launch Paralives to test.")


# ═══════════════════════════════════════════════════════════════════════════════════
#  INFO TEXT
# ═══════════════════════════════════════════════════════════════════════════════════

INFO_TEXT = """\
PARALIVES MOD TOOL  v2.0  —  Quick Guide
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GETTING STARTED
  Set your Main.mod Folder — the Main.mod directory.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEXTURE REPLACEMENT
  Browse to the .png inside your mod folder.

  Make Transparent
    Replaces with a fully transparent PNG.
    Useful for hiding clothing items.

  Replace with Custom
    Browse to your artwork and click Apply.
    Match the original size for best results.

  Requires:  pip install Pillow

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MESH REPLACEMENT
  Two modes are auto-detected:

  Same Topology  (shape morph)
    FBX vertex count ≈ original.
    Positions patched, bone weights kept.
    Export from Blender without adding or
    removing any vertices.

  Full Rebuild  (new mesh)
    FBX has a different vertex count.
    Positions, UVs, and bone weights are
    all read from the new FBX.
    Armature + skin weights required.

  Blender export settings for both modes:
    Limit to:  Selected Objects  ON
    Armature:  Apply Armature    OFF
               Only Deform Bones ON

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BACKUPS
  Every Apply creates a timestamped folder:
  Example structure:
    ParalivesBackupFiles/
      ExampleMesh.fbx/
        2025-06-01_14-30-00/
          ExampleMesh.fbx.import
          ExampleMesh.fbx.import.custom
          ExampleMesh.fbx.meta
          Species;Human;BodyParts.Metacache

  "Restore Latest" undoes the last Apply.
  "Open Backups" opens the folder in Explorer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHAT THE TOOL DOES INTERNALLY
  • Reads bone names from existing .import
    (nothing is hardcoded — works for any mesh)
  • Applies FBX→Unity winding fix so the
    game's RecalculateNormals() produces
    outward-facing normals (fixes dark colour)
  • Writes identical data to .import AND
    .import.custom
  • Updates .meta and _Metacache checksums
"""


# ═══════════════════════════════════════════════════════════════════════════════════
#  GUI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════════

def _divider(parent):
    ctk.CTkFrame(parent, fg_color=DIVIDER, height=1).pack(fill="x", padx=16, pady=6)

def _section_label(parent, text):
    ctk.CTkLabel(parent, text=text,
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=TXT_DIM, anchor="w"
                 ).pack(anchor="w", padx=16, pady=(8, 2))

def _hint_label(parent, text):
    ctk.CTkLabel(parent, text=text,
                 font=ctk.CTkFont(size=10),
                 text_color=TXT_DIM, anchor="w", justify="left"
                 ).pack(anchor="w", padx=16, pady=(0, 4))

def _white_btn(parent, text, cmd, **kw):
    return ctk.CTkButton(parent, text=text,
                         fg_color=WBTN, text_color=WBTN_TXT,
                         hover_color=WBTN_HOV, corner_radius=8,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         command=cmd, **kw)

def _grey_btn(parent, text, cmd, **kw):
    return ctk.CTkButton(parent, text=text,
                         fg_color=SBTN, text_color=TXT,
                         hover_color=SBTN_HOV, corner_radius=8,
                         font=ctk.CTkFont(size=12),
                         command=cmd, **kw)

def _file_row(parent, var, placeholder, browse_cmd):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=16, pady=(2, 4))
    ctk.CTkEntry(row, textvariable=var,
                 placeholder_text=placeholder,
                 fg_color=SURF3, text_color=TXT,
                 border_color=BORDER, border_width=1,
                 corner_radius=8, height=34,
                 font=ctk.CTkFont(size=11)
                 ).pack(side="left", fill="x", expand=True, padx=(0, 8))
    _grey_btn(row, "Browse", browse_cmd, width=78, height=34).pack(side="left")


# ═══════════════════════════════════════════════════════════════════════════════════
#  INFO DIALOG
# ═══════════════════════════════════════════════════════════════════════════════════

class InfoDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("How to Use")
        self.geometry("580x640")
        self.resizable(False, True)
        self.configure(fg_color=BG)
        self.grab_set(); self.lift(); self.focus_force()

        ctk.CTkLabel(self, text="How to Use",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TXT
                     ).pack(anchor="w", padx=24, pady=(22, 8))

        tb = ctk.CTkTextbox(self,
                            font=ctk.CTkFont(family="Courier New", size=11),
                            fg_color=SURF2, text_color=TXT,
                            border_color=BORDER, border_width=1,
                            corner_radius=10, wrap="word")
        tb.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        tb.insert("0.0", INFO_TEXT.strip())
        tb.configure(state="disabled")

        _white_btn(self, "Close", self.destroy, width=110, height=36
                   ).pack(pady=(0, 18))


# ═══════════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Paralives Mod Tool  v2.0")
        self.geometry("820x700")
        self.minsize(720, 580)
        self.configure(fg_color=BG)

        self._mod_folder = tk.StringVar()
        self._target_png = tk.StringVar()
        self._custom_png = tk.StringVar()
        self._target_fbx = tk.StringVar()
        self._new_fbx    = tk.StringVar()
        self._mode_text  = tk.StringVar(value="")

        # Auto-fill mod folder — try common locations in order
        _home = os.path.expanduser("~")
        _guesses = [
            os.path.join(_home, "Documents", "Games", "Paralives", "Main.mod"),
            os.path.join(_home, "AppData", "LocalLow", "Paralives Studio", "Paralives", "Main.mod"),
            os.path.join(_home, "AppData", "Roaming", "Paralives", "Main.mod"),
        ]
        for guess in _guesses:
            if os.path.isdir(guess):
                self._mod_folder.set(guess)
                break

        self._build()

        mf = self._mod_folder.get()
        if mf:
            self._log(f"Ready.  Mod folder: {mf}")
            self._log(f"Backups: {BACKUP_ROOT}")
        else:
            self._log("Ready.  Please set the Mod Folder above.")

    # ─────────────────────────────────────────────────────────────────────────────
    def _build(self):
        # ── Header ───────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="Paralives Mod Tool",
                     font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=TXT
                     ).pack(side="left", padx=22)
        ctk.CTkLabel(hdr, text="v2.0 by N0R0IK0",
                     font=ctk.CTkFont(size=11), text_color=TXT_DIM
                     ).pack(side="left", pady=(14, 0))
        _grey_btn(hdr, "  ? Info  ", self._show_info, width=90, height=32
                  ).pack(side="right", padx=16, pady=13)

        # ── Mod folder bar ────────────────────────────────────────────────────────
        fbar = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=12, height=54)
        fbar.pack(fill="x", padx=14, pady=(12, 0))
        fbar.pack_propagate(False)
        ctk.CTkLabel(fbar, text="Main.mod Folder",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TXT_DIM, width=84, anchor="w"
                     ).pack(side="left", padx=(14, 0))
        ctk.CTkEntry(fbar, textvariable=self._mod_folder,
                     fg_color=SURF3, text_color=TXT,
                     border_color=BORDER, border_width=1,
                     corner_radius=8, height=34,
                     font=ctk.CTkFont(size=12)
                     ).pack(side="left", fill="x", expand=True, padx=8)
        _grey_btn(fbar, "Browse", self._browse_mod_folder,
                  width=78, height=34).pack(side="left", padx=(0, 12))

        # ── Two cards ─────────────────────────────────────────────────────────────
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="both", expand=True, padx=14, pady=12)
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.rowconfigure(0, weight=1)

        self._build_texture_card(cards)
        self._build_mesh_card(cards)

        # ── Log ──────────────────────────────────────────────────────────────────
        lw = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=12)
        lw.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(lw, text="LOG",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM
                     ).pack(anchor="w", padx=14, pady=(8, 2))
        self._log_box = ctk.CTkTextbox(
            lw, height=112,
            fg_color=BG, text_color=TXT,
            font=ctk.CTkFont(family="Courier New", size=11),
            border_width=0, corner_radius=8)
        self._log_box.pack(fill="x", padx=8, pady=(0, 8))
        self._log_box.configure(state="disabled")

    # ─────────────────────────────────────────────────────────────────────────────
    def _build_texture_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=SURF, corner_radius=14)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(card, text="Texture",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TXT, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(card, text="Replace any in-game texture",
                     font=ctk.CTkFont(size=11), text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 8))
        _divider(card)

        _section_label(card, "TARGET TEXTURE")
        _hint_label(card, "The .png inside your mod folder to replace.")
        _file_row(card, self._target_png,
                  "Browse to a .png in your mod folder…",
                  self._browse_target_png)
        _divider(card)

        _section_label(card, "MAKE TRANSPARENT")
        ctk.CTkLabel(card,
                     text="Replaces the texture with a fully transparent\n"
                          "image — hides the item in-game.",
                     font=ctk.CTkFont(size=11), text_color=TXT_DIM,
                     justify="left", anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 8))
        _white_btn(card, "Make Transparent",
                   self._on_transparent, height=38
                   ).pack(fill="x", padx=16, pady=(0, 4))
        _divider(card)

        _section_label(card, "REPLACE WITH CUSTOM PNG")
        _hint_label(card, "Swap in your own artwork.")
        _file_row(card, self._custom_png,
                  "Browse to your custom .png…",
                  self._browse_custom_png)
        _white_btn(card, "Apply Custom Texture",
                   self._on_custom, height=38
                   ).pack(fill="x", padx=16, pady=(2, 10))

        if not HAS_PIL:
            w = ctk.CTkFrame(card, fg_color="#1e1600", corner_radius=8)
            w.pack(fill="x", padx=16, pady=(0, 14))
            ctk.CTkLabel(w, text="  Pillow not installed\n  Run:  pip install Pillow",
                         font=ctk.CTkFont(size=10), text_color="#fbbf24",
                         justify="left").pack(anchor="w", padx=10, pady=8)

    # ─────────────────────────────────────────────────────────────────────────────
    def _build_mesh_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=SURF, corner_radius=14)
        card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(card, text="Mesh",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TXT, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(card, text="Replace any in-game mesh",
                     font=ctk.CTkFont(size=11), text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 8))
        _divider(card)

        _section_label(card, "TARGET MESH")
        _hint_label(card, "The original .fbx inside your mod folder.")
        _file_row(card, self._target_fbx,
                  "Browse to a .fbx in your mod folder…",
                  self._browse_target_fbx)

        _section_label(card, "NEW MESH")
        _hint_label(card, "Your replacement .fbx (Blender export).")
        _file_row(card, self._new_fbx,
                  "Browse to your exported .fbx…",
                  self._browse_new_fbx)

        # Mode badge
        self._mode_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._mode_frame.pack(fill="x", padx=16, pady=(0, 6))
        self._mode_label = ctk.CTkLabel(
            self._mode_frame, textvariable=self._mode_text,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TXT_DIM, anchor="w")
        self._mode_label.pack(anchor="w")

        _divider(card)

        _white_btn(card, "Apply Mesh",
                   self._on_mesh, height=40
                   ).pack(fill="x", padx=16, pady=(4, 6))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        _grey_btn(btn_row, "Restore Latest",
                  self._on_restore, height=34
                  ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        _grey_btn(btn_row, "Open Backups",
                  self._on_open_backups, height=34
                  ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Blender reminder
        note = ctk.CTkFrame(card, fg_color=SURF2, corner_radius=10)
        note.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkLabel(note,
                     text="Blender export  ▸  Selected Objects: ON\n"
                          "Apply Armature: OFF  /  Only Deform Bones: ON",
                     font=ctk.CTkFont(family="Courier New", size=10),
                     text_color=TXT_DIM, justify="left"
                     ).pack(anchor="w", padx=12, pady=10)

    # ─────────────────────────────────────────────────────────────────────────────
    #  Browse handlers
    # ─────────────────────────────────────────────────────────────────────────────
    def _show_info(self): InfoDialog(self)

    def _browse_mod_folder(self):
        d = filedialog.askdirectory(title="Select Main.mod folder")
        if d: self._mod_folder.set(d)

    def _idir(self):
        d = self._mod_folder.get().strip()
        return d if os.path.isdir(d) else os.path.expanduser("~")

    def _browse_target_png(self):
        p = filedialog.askopenfilename(
            title="Select target texture", initialdir=self._idir(),
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if p: self._target_png.set(p)

    def _browse_custom_png(self):
        p = filedialog.askopenfilename(
            title="Select your custom PNG",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if p: self._custom_png.set(p)

    def _browse_target_fbx(self):
        p = filedialog.askopenfilename(
            title="Select target mesh (.fbx in mod folder)", initialdir=self._idir(),
            filetypes=[("FBX files", "*.fbx"), ("All files", "*.*")])
        if p:
            self._target_fbx.set(p)
            self._update_mode_badge()

    def _browse_new_fbx(self):
        p = filedialog.askopenfilename(
            title="Select your replacement FBX",
            filetypes=[("FBX files", "*.fbx"), ("All files", "*.*")])
        if p:
            self._new_fbx.set(p)
            self._update_mode_badge()

    def _update_mode_badge(self):
        """Show Same Topology / Full Rebuild badge based on vertex counts."""
        fbx  = self._target_fbx.get().strip()
        nfbx = self._new_fbx.get().strip()
        imp  = fbx + ".import"

        if not fbx or not os.path.exists(imp):
            self._mode_text.set("")
            return
        try:
            with open(imp, "rb") as f: d = f.read(4)
            V_orig = struct.unpack_from("<i", d, 0)[0]
            if nfbx and os.path.exists(nfbx):
                n_fbx = _quick_fbx_vert_count(nfbx)
                if n_fbx > 0:
                    ratio = n_fbx / max(V_orig, 1)
                    if 0.85 <= ratio <= 1.15:
                        self._mode_text.set(
                            f"▸ Same Topology  (target {V_orig} / FBX {n_fbx})")
                        self._mode_label.configure(text_color=BADGE_A_T)
                    else:
                        self._mode_text.set(
                            f"▸ Full Rebuild  (target {V_orig} / FBX {n_fbx})")
                        self._mode_label.configure(text_color=BADGE_B_T)
                    return
            self._mode_text.set(f"Target: {V_orig} vertices")
            self._mode_label.configure(text_color=TXT_DIM)
        except Exception:
            self._mode_text.set("")

    # ─────────────────────────────────────────────────────────────────────────────
    #  Action handlers
    # ─────────────────────────────────────────────────────────────────────────────
    def _on_transparent(self):
        png = self._target_png.get().strip()
        if not self._chk_modfolder(): return
        if not self._chk_file(png, ".png", "Target Texture"): return
        if not self._chk_meta(png): return
        self._run(apply_transparent, png, self._mod_folder.get())

    def _on_custom(self):
        png = self._target_png.get().strip()
        cus = self._custom_png.get().strip()
        if not self._chk_modfolder(): return
        if not self._chk_file(png, ".png", "Target Texture"): return
        if not self._chk_meta(png): return
        if not self._chk_file(cus, ".png", "Custom PNG"): return
        self._run(apply_custom_texture, png, cus, self._mod_folder.get())

    def _on_mesh(self):
        self._log("Apply Mesh clicked")
        fbx  = self._target_fbx.get().strip()
        nfbx = self._new_fbx.get().strip()
        if not self._chk_modfolder(): return
        if not self._chk_file(fbx, ".fbx",  "Target Mesh"): return
        if not self._chk_meta(fbx): return
        if not self._chk_file(nfbx, ".fbx", "New Mesh"): return
        if not os.path.exists(fbx + ".import"):
            self._log(f"ERROR: No .import file found next to: {fbx}")
            messagebox.showerror("Missing File",
                f"No .import file found next to:\n{fbx}\n\n"
                "Make sure you selected the .fbx inside your mod folder.",
                parent=self)
            return
        self._run(apply_mesh, fbx, nfbx, self._mod_folder.get())

    def _on_restore(self):
        fbx = self._target_fbx.get().strip()
        if not self._chk_modfolder(): return
        if not self._chk_file(fbx, ".fbx", "Target Mesh"): return
        self._run(restore_latest_mesh_backup, fbx, self._mod_folder.get())

    def _on_open_backups(self):
        fbx = self._target_fbx.get().strip()
        if fbx:
            folder = os.path.join(BACKUP_ROOT, os.path.basename(fbx))
        else:
            folder = BACKUP_ROOT
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    # ─────────────────────────────────────────────────────────────────────────────
    #  Validation
    # ─────────────────────────────────────────────────────────────────────────────
    def _chk_modfolder(self):
        d = self._mod_folder.get().strip()
        if not d or not os.path.isdir(d):
            msg = "Please set the Mod Folder to your Main.mod directory first."
            self._log(f"ERROR: Mod Folder not set or invalid — {d!r}")
            messagebox.showerror("Mod Folder Not Set", msg, parent=self)
            return False
        return True

    def _chk_file(self, path, ext, label):
        if not path:
            self._log(f"ERROR: No file selected for: {label}")
            messagebox.showerror("Missing File",
                f"No file selected for: {label}\n\nClick Browse to select a file.",
                parent=self)
            return False
        if not os.path.exists(path):
            self._log(f"ERROR: File not found — {path}")
            messagebox.showerror("File Not Found",
                f"{label}\n\nFile not found:\n{path}",
                parent=self)
            return False
        if not path.lower().endswith(ext):
            self._log(f"ERROR: Wrong file type for {label} — expected {ext}, got {os.path.basename(path)}")
            messagebox.showerror("Wrong File Type",
                f"{label}\n\nExpected a {ext} file.\nSelected: {os.path.basename(path)}",
                parent=self)
            return False
        return True

    def _chk_meta(self, asset_path):
        meta = asset_path + ".meta"
        if not os.path.exists(meta):
            self._log(f"ERROR: No .meta sidecar found for: {asset_path}")
            messagebox.showerror("No .meta File",
                f"No .meta sidecar found for:\n{asset_path}\n\n"
                "Make sure you selected the file INSIDE Main.mod.",
                parent=self)
            return False
        return True

    # ─────────────────────────────────────────────────────────────────────────────
    #  Threading + Log
    # ─────────────────────────────────────────────────────────────────────────────
    def _run(self, func, *args):
        self._log("─" * 44)
        def worker():
            try:
                func(*args, log=self._log)
            except Exception as e:
                self._log(f"ERROR: {e}")
                self.after(0, lambda e=e: messagebox.showerror("Error", str(e), parent=self))
        threading.Thread(target=worker, daemon=True).start()

    def _log(self, msg):
        def _do():
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
        self.after(0, _do)


# ═══════════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()
