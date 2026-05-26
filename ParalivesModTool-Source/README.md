# Paralives Mod Tool — Source Code
**by N0R0IK0**  
Nexus Mods page: https://www.nexusmods.com/paralives/mods/22

---

## What this tool does

A standalone GUI utility for the game **Paralives** that lets users:
- Replace in-game clothing textures (make them transparent, or swap in custom PNG artwork)
- Replace body/clothing meshes with versions edited in Blender

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
| Imports & dependency check | 1–25 | Standard library + customtkinter + Pillow |
| Colour palette | 27–40 | UI colour constants |
| Core logic — shared | 46–83 | SHA1 hashing, meta/metacache checksum patching |
| Core logic — textures | 87–136 | Generate Y-flipped import files, update checksums |
| Core logic — meshes | 140–260 | FBX binary parser, vertex mapping, normal recalc, import file patching |
| UI — InfoDialog | ~270 | Help/guide popup window |
| UI — App | ~320 | Main window: header, folder bar, texture card, mesh card, log |
| Entry point | last line | `App().mainloop()` |

### Key logic — textures
The game stores pre-compiled `.import` files alongside each `.png` (full-res, 50%, 25%, 12.5%). When a texture is replaced, the tool:
1. Saves the new PNG
2. Regenerates all four `.import` files (Y-flipped, as the engine expects)
3. Updates the SHA1 checksum in the `.meta` sidecar file and the `Main.mod.metacache` index

### Key logic — meshes
The game stores a pre-compiled binary `.fbx.import` file alongside each `.fbx`. The tool:
1. Reads vertex positions from the user's new FBX (custom binary FBX parser using `struct` + `zlib`, no third-party FBX library)
2. Builds a mapping from import-file vertex indices to FBX vertex indices by matching 3D positions
3. Patches only the vertex positions and recalculated normals into the existing binary import file
4. Leaves the bone weight section, UV data, triangle indices, and tangent section completely untouched
5. Saves a `.bak` backup before writing anything

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

The output exe will appear in the `dist\` folder. It is identical to the file distributed on Nexus Mods.

---

## Files in this repository

```
paralives_mod_tool.py   — full source code (single file, ~730 lines)
requirements.txt        — pip dependencies
build.bat               — one-click build script for Windows
README.md               — this file
```

---

## License

Free to use, modify, and redistribute. Credit appreciated but not required.
