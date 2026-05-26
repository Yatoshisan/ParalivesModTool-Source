#!/usr/bin/env python3
"""
Paralives Mod Tool  v1.1 by N0R0IK0
Requires:  pip install customtkinter pillow
"""

import os, re, sys, json, struct, zlib, hashlib, math, shutil, threading
import tkinter as tk
from tkinter import filedialog

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

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#0d0d0d"
SURF     = "#161616"
SURF2    = "#1e1e1e"
SURF3    = "#272727"
BORDER   = "#2e2e2e"
TXT      = "#f0f0f0"
TXT_DIM  = "#5a5a5a"
WBTN     = "#ececec"
WBTN_TXT = "#0d0d0d"
WBTN_HOV = "#d0d0d0"
SBTN     = "#252525"
SBTN_HOV = "#333333"
DIVIDER  = "#2a2a2a"

# ═══════════════════════════════════════════════════════════════════════════════
#  CORE LOGIC  (unchanged from working version)
# ═══════════════════════════════════════════════════════════════════════════════

def sha1_of(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest().upper()

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

def update_metacache_checksum(cache_path, asset_rel, new_cs):
    with open(cache_path, "r", encoding="utf-8") as f:
        mc = f.read()
    if asset_rel not in mc:
        raise ValueError(f"Asset key not found in metacache:\n{asset_rel}")
    idx      = mc.index(asset_rel)
    cs_start = mc.index("ImportFileCheckSum:", idx)
    cs_end   = mc.index("\n", cs_start)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(mc[:cs_start] + f"ImportFileCheckSum:{new_cs}" + mc[cs_end:])

def find_metacache(mod_folder):
    for fname in os.listdir(mod_folder):
        if fname.endswith(".metacache"):
            return os.path.join(mod_folder, fname)
    raise FileNotFoundError("No .metacache file found in the mod folder.")

def asset_rel(mod_folder, asset_path):
    return os.path.relpath(asset_path, mod_folder).replace("\\", "/")

# ── Texture ops ───────────────────────────────────────────────────────────────

def _write_imports(png_path, img, log):
    w, h = img.size
    for suffix, factor in [("", 1.0), ("5", 0.5), ("25", 0.25), ("125", 0.125)]:
        nw = max(1, int(w * factor))
        nh = max(1, int(h * factor))
        out = img.resize((nw, nh), PILImage.LANCZOS) if factor != 1.0 else img.copy()
        out = out.transpose(PILImage.FLIP_TOP_BOTTOM)
        ext = f".{suffix}.import" if suffix else ".import"
        out.save(png_path + ext, "PNG")
        log(f"  {os.path.basename(png_path) + ext}")

def apply_transparent(png_path, mod_folder, log):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed — run:  pip install Pillow")
    meta = png_path + ".meta"
    ow = read_meta_value(meta, "OriginalWidth")
    oh = read_meta_value(meta, "OriginalHeight")
    if ow and oh:
        w, h = int(ow), int(oh)
    else:
        tmp = PILImage.open(png_path); w, h = tmp.size; tmp.close()
    log(f"Creating transparent image ({w}x{h})...")
    img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
    img.save(png_path, "PNG")
    log(f"  Saved {os.path.basename(png_path)}")
    _write_imports(png_path, img, log)
    cs = sha1_of(png_path)
    update_meta_checksum(meta, cs)
    update_metacache_checksum(find_metacache(mod_folder),
                              asset_rel(mod_folder, png_path), cs)
    log(f"  Checksum updated.")
    log(f"Done — launch Paralives to test.")

def apply_custom_texture(png_path, custom_png, mod_folder, log):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed — run:  pip install Pillow")
    meta = png_path + ".meta"
    log(f"Loading: {os.path.basename(custom_png)}")
    img = PILImage.open(custom_png).convert("RGBA")
    log(f"  Size: {img.size[0]}x{img.size[1]}")
    img.save(png_path, "PNG")
    log(f"  Replaced {os.path.basename(png_path)}")
    _write_imports(png_path, img, log)
    img.close()
    cs = sha1_of(png_path)
    update_meta_checksum(meta, cs)
    update_metacache_checksum(find_metacache(mod_folder),
                              asset_rel(mod_folder, png_path), cs)
    log(f"  Checksum updated.")
    log(f"Done — launch Paralives to test.")

# ── Mesh ops ──────────────────────────────────────────────────────────────────

def _read_fbx_verts(path):
    with open(path, "rb") as f:
        data = f.read()
    def rnode(o):
        if o + 13 > len(data): return None, o
        end = struct.unpack_from("<I", data, o)[0]
        if end == 0: return None, o + 13
        pl = struct.unpack_from("<I", data, o+8)[0]
        nl = data[o+12]
        name = data[o+13:o+13+nl].decode("ascii", errors="replace")
        return {"name": name, "end": end, "ps": o+13+nl, "pl": pl}, end
    def rarr(o):
        tc = chr(data[o]); o += 1
        cnt, enc, cl = struct.unpack_from("<III", data, o); o += 12
        raw = data[o:o+cl]
        if enc == 1: raw = zlib.decompress(raw)
        fmt = "d" if tc == "d" else "f"
        return list(struct.unpack_from(f"<{cnt}{fmt}", raw))
    o = 27
    while o < len(data):
        node, no = rnode(o)
        if node is None: break
        if node["name"] == "Objects":
            co = node["ps"] + node["pl"]
            while co < node["end"]:
                ch, _ = rnode(co)
                if ch is None: break
                if ch["name"] == "Geometry":
                    gc = ch["ps"] + ch["pl"]
                    while gc < ch["end"]:
                        g, _ = rnode(gc)
                        if g is None: break
                        if g["name"] == "Vertices":
                            raw = rarr(g["ps"])
                            return [(raw[i], raw[i+1], raw[i+2])
                                    for i in range(0, len(raw), 3)]
                        gc = g["end"]
                co = ch["end"]
        o = no
    return []

def _f32(v):  return struct.unpack("<f", struct.pack("<f", v))[0]
def _norm(v):
    l = math.sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2])
    return (v[0]/l, v[1]/l, v[2]/l) if l > 1e-10 else (0., 1., 0.)
def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _add(a, b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

def apply_mesh(fbx_path, new_fbx_path, mod_folder, log):
    imp_path  = fbx_path + ".import"
    meta_path = fbx_path + ".meta"
    bak_path  = imp_path + ".bak"
    store     = os.path.join(mod_folder, ".modtool")
    os.makedirs(store, exist_ok=True)
    name      = os.path.splitext(os.path.basename(fbx_path))[0]
    map_file  = os.path.join(store, name + ".mapping.json")
    cs_file   = os.path.join(store, name + ".orig_cs")

    if not os.path.exists(imp_path):
        raise FileNotFoundError(f"Import file not found:\n{imp_path}")

    # Preserve original checksum on first use
    if not os.path.exists(cs_file):
        orig_cs = read_meta_value(meta_path, "ImportFileCheckSum") or ""
        with open(cs_file, "w") as f: f.write(orig_cs)
    else:
        with open(cs_file) as f: orig_cs = f.read().strip()

    log(f"Reading FBX: {os.path.basename(new_fbx_path)}")
    new_fbx = _read_fbx_verts(new_fbx_path)
    if not new_fbx:
        raise ValueError("No vertices found in the FBX — check the file.")
    log(f"  FBX vertices: {len(new_fbx)}")

    shutil.copy2(imp_path, bak_path)
    log(f"  Backup saved.")

    with open(bak_path, "rb") as f: bak = bytearray(f.read())
    with open(imp_path,  "rb") as f: imp = bytearray(f.read())

    V       = struct.unpack_from("<I", imp, 0)[0]
    bak_pos = [struct.unpack_from("<fff", bak, 4 + i*12) for i in range(V)]
    I_cnt   = struct.unpack_from("<I", bak, 0x1D08)[0]
    indices = list(struct.unpack_from(f"<{I_cnt}I", bak, 0x1D0C))
    T       = I_cnt // 3
    log(f"  Import: {V} vertices, {T} triangles")

    if os.path.exists(map_file):
        log(f"  Loading saved vertex mapping...")
        with open(map_file) as f: i2f = json.load(f)
    else:
        log(f"  Building vertex mapping...")
        nf32 = [(_f32(x), _f32(y), _f32(z)) for x, y, z in new_fbx]
        i2f  = [-1] * V
        for ii, (ix, iy, iz) in enumerate(bak_pos):
            bd, bj = 0.06, -1
            for j, (fx, fy, fz) in enumerate(nf32):
                d = abs(-fx-ix)+abs(fy-iy)+abs(fz-iz)
                if d < bd: bd, bj = d, j
            i2f[ii] = bj
        with open(map_file, "w") as f: json.dump(i2f, f)
        log(f"  Mapping saved.")

    matched = sum(1 for j in i2f if j >= 0)
    log(f"  Matched {matched}/{V} vertices" +
        (f" ({V-matched} kept from backup)" if matched < V else ""))

    new_pos = []
    for ii in range(V):
        j = i2f[ii]
        if 0 <= j < len(new_fbx):
            fx, fy, fz = new_fbx[j]
            new_pos.append((_f32(-fx), _f32(fy), _f32(fz)))
        else:
            new_pos.append(bak_pos[ii])

    for i, (x, y, z) in enumerate(new_pos):
        struct.pack_into("<fff", imp, 4 + i*12, x, y, z)

    log(f"  Recalculating normals...")
    nacc = [(0., 0., 0.)] * V
    for t in range(T):
        i0, i1, i2 = indices[t*3], indices[t*3+1], indices[t*3+2]
        fn = _cross(_sub(new_pos[i1], new_pos[i0]), _sub(new_pos[i2], new_pos[i0]))
        nacc[i0] = _add(nacc[i0], fn)
        nacc[i1] = _add(nacc[i1], fn)
        nacc[i2] = _add(nacc[i2], fn)
    for i, n in enumerate(nacc):
        nx, ny, nz = _norm(n)
        struct.pack_into("<fff", imp, 0x4FE0 + i*12, nx, ny, nz)

    imp[0x8044:0xA6F4] = bak[0x8044:0xA6F4]  # restore proprietary tangent section

    with open(imp_path, "wb") as f: f.write(imp)
    log(f"  Import file written ({len(imp):,} bytes).")

    if orig_cs:
        update_meta_checksum(meta_path, orig_cs)
        try:
            update_metacache_checksum(find_metacache(mod_folder),
                                      asset_rel(mod_folder, fbx_path), orig_cs)
            log(f"  Checksum restored.")
        except Exception as e:
            log(f"  Warning: {e}")

    log(f"Done — launch Paralives to test.")


# ═══════════════════════════════════════════════════════════════════════════════
#  INFO TEXT
# ═══════════════════════════════════════════════════════════════════════════════

INFO_TEXT = """\
PARALIVES MOD TOOL  —  Quick Guide
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GETTING STARTED
  Set your mod folder (the Main.mod directory).
  It's usually found at:
    Documents/Games/Paralives/Main.mod

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEXTURE REPLACEMENT
  1. Click Browse next to "Target Texture" and
     navigate to the .png file inside your mod
     folder that you want to replace.

  Make Transparent
     Replaces the image with a fully transparent
     PNG — hides the clothing item in-game.

  Replace with Custom
     Browse to your own PNG artwork and click
     Apply. Match the original image size for
     best results.

  Requires:  pip install Pillow

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MESH REPLACEMENT
  Requires Blender (blender.org — it's free).

  Step 1 — Edit in Blender
    • File > Import > FBX — load the original mesh
    • Edit the shape (move vertices, Shrinkwrap…)
      !! Do NOT add or remove vertices !!
    • File > Export > FBX with these settings:
        Limit to:  Selected Objects   ON
        Armature:  Apply Armature     OFF
                   Only Deform Bones  ON

  Step 2 — Apply here
    • Browse to the original .fbx inside the mod
      folder (Target Mesh)
    • Browse to your exported .fbx (New FBX)
    • Click Apply

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BACKUPS
  Every Apply saves a .bak copy of the original
  import file. To revert: rename .bak → .import.
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════════

def _divider(parent):
    ctk.CTkFrame(parent, fg_color=DIVIDER, height=1
                 ).pack(fill="x", padx=16, pady=8)

def _label(parent, text, size=11, bold=False, dim=False, **kw):
    ctk.CTkLabel(parent, text=text,
                 font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"),
                 text_color=TXT_DIM if dim else TXT,
                 **kw).pack(**{"anchor": "w", "padx": 16, "pady": (6, 2)})

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
    row.pack(fill="x", padx=16, pady=(2, 6))
    ctk.CTkEntry(row, textvariable=var,
                 placeholder_text=placeholder,
                 fg_color=SURF3, text_color=TXT,
                 border_color=BORDER, border_width=1,
                 corner_radius=8, height=34,
                 font=ctk.CTkFont(size=11)
                 ).pack(side="left", fill="x", expand=True, padx=(0, 8))
    _grey_btn(row, "Browse", browse_cmd, width=78, height=34).pack(side="left")


class InfoDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("How to Use")
        self.geometry("560x600")
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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Paralives Mod Tool")
        self.geometry("780x660")
        self.minsize(680, 560)
        self.configure(fg_color=BG)

        self._mod_folder  = tk.StringVar()
        self._target_png  = tk.StringVar()
        self._custom_png  = tk.StringVar()
        self._target_fbx  = tk.StringVar()
        self._new_fbx     = tk.StringVar()

        guess = os.path.join(os.path.expanduser("~"),
                             "Documents", "Games", "Paralives", "Main.mod")
        if os.path.isdir(guess):
            self._mod_folder.set(guess)

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="Paralives Mod Tool",
                     font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=TXT
                     ).pack(side="left", padx=22)
        ctk.CTkLabel(hdr, text="v1.1 by N0R0IK0",
                     font=ctk.CTkFont(size=11),
                     text_color=TXT_DIM
                     ).pack(side="left", pady=(14, 0))
        _grey_btn(hdr, "  ? Info  ", self._show_info,
                  width=90, height=32
                  ).pack(side="right", padx=16, pady=13)

        # Mod folder
        fbar = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=12, height=54)
        fbar.pack(fill="x", padx=14, pady=(12, 0))
        fbar.pack_propagate(False)
        ctk.CTkLabel(fbar, text="Mod Folder",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TXT_DIM, width=82, anchor="w"
                     ).pack(side="left", padx=(14, 0))
        ctk.CTkEntry(fbar, textvariable=self._mod_folder,
                     fg_color=SURF3, text_color=TXT,
                     border_color=BORDER, border_width=1,
                     corner_radius=8, height=34,
                     font=ctk.CTkFont(size=12)
                     ).pack(side="left", fill="x", expand=True, padx=8)
        _grey_btn(fbar, "Browse", self._browse_mod_folder,
                  width=78, height=34
                  ).pack(side="left", padx=(0, 12))

        # Two cards
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="both", expand=True, padx=14, pady=12)
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.rowconfigure(0, weight=1)

        self._build_texture_card(cards)
        self._build_mesh_card(cards)

        # Log
        log_wrap = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=12)
        log_wrap.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(log_wrap, text="LOG",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM
                     ).pack(anchor="w", padx=14, pady=(8, 2))
        self._log_box = ctk.CTkTextbox(
            log_wrap, height=106,
            fg_color=BG, text_color=TXT,
            font=ctk.CTkFont(family="Courier New", size=11),
            border_width=0, corner_radius=8)
        self._log_box.pack(fill="x", padx=8, pady=(0, 8))
        self._log_box.configure(state="disabled")

    def _build_texture_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=SURF, corner_radius=14)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(card, text="Texture",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TXT, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(card, text="Replace a clothing texture",
                     font=ctk.CTkFont(size=11),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 10))

        _divider(card)

        # Target PNG
        ctk.CTkLabel(card, text="TARGET TEXTURE",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(2, 2))
        ctk.CTkLabel(card, text="The .png file inside your mod folder to replace.",
                     font=ctk.CTkFont(size=10),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 4))
        _file_row(card, self._target_png,
                  "Browse to a .png in your mod folder...",
                  self._browse_target_png)

        _divider(card)

        # Make transparent
        ctk.CTkLabel(card, text="MAKE TRANSPARENT",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(2, 2))
        ctk.CTkLabel(card,
                     text="Replaces the texture with an invisible image.\nIdeal for hiding clothing items.",
                     font=ctk.CTkFont(size=11), text_color=TXT_DIM,
                     justify="left", anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 8))
        _white_btn(card, "Make Transparent",
                   self._on_transparent, height=38
                   ).pack(fill="x", padx=16, pady=(0, 4))

        _divider(card)

        # Custom PNG
        ctk.CTkLabel(card, text="REPLACE WITH CUSTOM PNG",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(2, 2))
        ctk.CTkLabel(card, text="Swap in your own artwork.",
                     font=ctk.CTkFont(size=11), text_color=TXT_DIM,
                     anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 4))
        _file_row(card, self._custom_png,
                  "Browse to your custom .png...",
                  self._browse_custom_png)
        _white_btn(card, "Apply Custom Texture",
                   self._on_custom, height=38
                   ).pack(fill="x", padx=16, pady=(2, 16))

        if not HAS_PIL:
            warn = ctk.CTkFrame(card, fg_color="#1e1600", corner_radius=8)
            warn.pack(fill="x", padx=16, pady=(0, 14))
            ctk.CTkLabel(warn,
                         text="  Pillow not installed\n  Run:  pip install Pillow",
                         font=ctk.CTkFont(size=10), text_color="#fbbf24",
                         justify="left"
                         ).pack(anchor="w", padx=10, pady=8)

    def _build_mesh_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=SURF, corner_radius=14)
        card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(card, text="Mesh",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TXT, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(card, text="Replace a body or clothing mesh",
                     font=ctk.CTkFont(size=11),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 10))

        _divider(card)

        # Target FBX
        ctk.CTkLabel(card, text="TARGET MESH",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(2, 2))
        ctk.CTkLabel(card, text="The original .fbx file inside your mod folder.",
                     font=ctk.CTkFont(size=10),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 4))
        _file_row(card, self._target_fbx,
                  "Browse to a .fbx in your mod folder...",
                  self._browse_target_fbx)

        _divider(card)

        # New FBX
        ctk.CTkLabel(card, text="NEW FBX",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(2, 2))
        ctk.CTkLabel(card, text="Your edited FBX exported from Blender.",
                     font=ctk.CTkFont(size=10),
                     text_color=TXT_DIM, anchor="w"
                     ).pack(anchor="w", padx=16, pady=(0, 4))
        _file_row(card, self._new_fbx,
                  "Browse to your exported .fbx...",
                  self._browse_new_fbx)

        _divider(card)

        _white_btn(card, "Apply Mesh Replacement",
                   self._on_mesh, height=38
                   ).pack(fill="x", padx=16, pady=(4, 10))

        # Blender reminder
        note = ctk.CTkFrame(card, fg_color=SURF2, corner_radius=10)
        note.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkLabel(note,
                     text="Blender export  →  Selected Objects: ON\n"
                          "Armature: Apply OFF  /  Only Deform Bones: ON\n"
                          "Vertex count must stay the same",
                     font=ctk.CTkFont(family="Courier New", size=10),
                     text_color=TXT_DIM, justify="left"
                     ).pack(anchor="w", padx=12, pady=10)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _show_info(self): InfoDialog(self)

    def _browse_mod_folder(self):
        d = filedialog.askdirectory(title="Select Main.mod folder")
        if d: self._mod_folder.set(d)

    def _idir(self):
        """Initial directory for file pickers — mod folder if set."""
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
            title="Select target mesh", initialdir=self._idir(),
            filetypes=[("FBX files", "*.fbx"), ("All files", "*.*")])
        if p: self._target_fbx.set(p)

    def _browse_new_fbx(self):
        p = filedialog.askopenfilename(
            title="Select your exported FBX",
            filetypes=[("FBX files", "*.fbx"), ("All files", "*.*")])
        if p: self._new_fbx.set(p)

    def _on_transparent(self):
        png = self._target_png.get().strip()
        if not self._validate_file(png, ".png", "target texture"): return
        if not self._validate_meta(png): return
        self._run(apply_transparent, png, self._mod_folder.get())

    def _on_custom(self):
        png    = self._target_png.get().strip()
        custom = self._custom_png.get().strip()
        if not self._validate_file(png, ".png", "target texture"): return
        if not self._validate_meta(png): return
        if not self._validate_file(custom, ".png", "custom PNG"): return
        self._run(apply_custom_texture, png, custom, self._mod_folder.get())

    def _on_mesh(self):
        fbx     = self._target_fbx.get().strip()
        new_fbx = self._new_fbx.get().strip()
        if not self._validate_file(fbx, ".fbx", "target mesh"): return
        if not self._validate_meta(fbx): return
        if not self._validate_file(new_fbx, ".fbx", "new FBX"): return
        self._run(apply_mesh, fbx, new_fbx, self._mod_folder.get())

    # ── Validation helpers ────────────────────────────────────────────────────

    def _validate_file(self, path, ext, label):
        if not path:
            self._log(f"ERROR: No {label} selected."); return False
        if not os.path.exists(path):
            self._log(f"ERROR: File not found — {path}"); return False
        if not path.lower().endswith(ext):
            self._log(f"ERROR: Expected a {ext} file for {label}."); return False
        return True

    def _validate_meta(self, asset_path):
        meta = asset_path + ".meta"
        if not os.path.exists(meta):
            self._log(f"ERROR: No .meta file found next to:\n  {asset_path}")
            return False
        return True

    # ── Threading + Log ───────────────────────────────────────────────────────

    def _run(self, func, *args):
        self._log("─" * 40)
        def worker():
            try:
                func(*args, log=self._log)
            except Exception as e:
                self._log(f"ERROR: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _log(self, msg):
        def _do():
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
        self.after(0, _do)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()
