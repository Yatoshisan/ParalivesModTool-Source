# Paralives Mod Tool — Source Code
**by N0R0IK0**  
Nexus Mods page: https://www.nexusmods.com/paralives/mods/22

---

## What this tool does

A standalone GUI utility for the game **Paralives** that lets users:
- Replace any in-game texture (make it transparent, or swap in custom PNG artwork)
- Replace any in-game mesh with a version edited in Blender — body parts, clothing, buildings, props, signs, and more

The tool reads and writes files inside the user's local `Main.mod` folder. It makes **no network requests**, writes **no registry entries**, and touches **no system files**. All file operations are limited to the mod folder the user points it at.

---

## Why the exe triggers antivirus scanners

The distributed `.exe` was compiled using **PyInstaller** (`--onefile --windowed`), which bundles the Python interpreter, the script, and all dependencies into a single executable. This packaging method is well-documented to produce false positives in antivirus software because the PyInstaller bootloader unpacks itself into a temp directory at runtime — behaviour that scanners sometimes flag as suspicious regardless of the actual content.

References:
- https://github.com/pyinstaller/pyinstaller/issues/5932
- https://www.virustotal.com (searching "pyinstaller false positive" returns thousands of legitimate tools with the same issue)

---

## Source code overview

Everything is contained in a single file: **`paralives_mod_tool.py`**

| Section | Lines | Description |
|---|---|---|
| Imports & dependency check | 1–35 | Standard library + customtkinter + Pillow |
| Colour palette | 37–54 | UI colour constants |
| Backup system | 61–110 | `create_backup()`, `latest_backup_dir()`, `_backup_slot()` |
| Core logic — shared | 112–190 | SHA1 hashing, meta/metacache checksum patching (binary-safe) |
| Core logic — import parser | 192–245 | `parse_import_info()`: reads vertex/index/UV/bone-weight counts and offsets from existing `.import` binary |
| Core logic — FBX parser | 247–455 | `read_fbx_geometry()`, `read_fbx_bone_weights()`: custom binary FBX parser using `struct` + `zlib`, no third-party library |
| Core logic — import builder | 457–567 | `build_import_vertices()`, `build_import_binary()`: constructs `.import` / `.import.custom` from scratch |
| Core logic — mesh ops | 569–771 | `_same_topology_patch()`, `_full_rebuild()`, `apply_mesh()`, `restore_latest_mesh_backup()` |
| Core logic — textures | 773–833 | Y-flipped import file generation, checksum updates |
| Info text | 836–912 | In-app help/guide content |
| UI helpers | 914–958 | Shared widget factory functions |
| UI — InfoDialog | 960–989 | Help popup window |
| UI — App | 991–1389 | Main window: header, folder bar, texture card, mesh card, log |

### Key logic — textures

The game stores pre-compiled `.import` files alongside each `.png` (full-res, 50%, 25%, 12.5%). When a texture is replaced, the tool:
1. Saves the new PNG
2. Regenerates all four `.import` files (Y-flipped, as the engine expects)
3. Updates the SHA1 checksum in the `.meta` sidecar and the `_Metacache` index file

### Key logic — meshes

The game stores a pre-compiled binary `.fbx.import` (geometry) and `.fbx.import.custom` (bone weights) alongside each `.fbx`. When a mesh is applied, the tool auto-detects which of two modes to use:

**Same Topology** — new mesh is within ±15% of the original vertex count:
1. Reads vertex positions from the user's FBX using the custom binary parser
2. Builds a nearest-vertex mapping from import indices to FBX vertices
3. Patches only the positions and recalculated normals into the existing binary
4. Preserves UV data, triangle indices, bone weights, and tangent sections exactly

**Full Rebuild** — new mesh has a significantly different vertex count:
1. Reads full geometry (positions, UVs, face topology) and bone weights from the FBX
2. Constructs a brand-new `.import` binary from scratch, including correctly wound triangle indices
3. Remaps bone weights from the original mesh by nearest-vertex matching
4. Writes both `.import` and `.import.custom` in full

In both modes, the FBX→Unity coordinate conversion (negate X) reverses triangle winding. The tool applies a **v1↔v2 swap** on every triangle to restore correct CCW winding so the engine's `RecalculateNormals()` produces outward-facing normals.

---

## Dependencies

| Package | Purpose |
|---|---|
| `customtkinter` | Modern dark-theme UI widgets |
| `Pillow` | PNG reading/writing and resizing for texture import generation |
| `pyinstaller` | Build-time only — packages the script into a standalone exe |

No dependency makes network requests. All three are available on PyPI.

---

## How to run from source

```
pip install customtkinter Pillow
python paralives_mod_tool.py
```

Requires Python 3.10 or newer.

---

## How to build the exe yourself

**Option A — double-click:**
```
build.bat
```

**Option B — manual:**
```
pip install customtkinter Pillow pyinstaller
python -m PyInstaller --onefile --windowed --collect-all customtkinter --name "ParalivesModTool" paralives_mod_tool.py
```

The output exe will appear in the `dist\` folder (or the parent folder if using `build.bat`). It is identical to the file distributed on Nexus Mods.

---

## Files in this repository

```
paralives_mod_tool.py   — full source code (single file, ~1391 lines)
requirements.txt        — pip dependencies
build.bat               — one-click build script for Windows
README.md               — this file
```

---

## License

Free to use and share. Credit required.
