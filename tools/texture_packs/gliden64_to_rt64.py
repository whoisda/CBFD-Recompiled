#!/usr/bin/env python3
"""
Converts a GLideN64 texture pack (for Project64, RetroArch's Mupen64Plus-Next...) to an RT64
texture pack for Conker's Bad Fur Day: Recompiled, with only Python's standard library:

  python tools/texture_packs/gliden64_to_rt64.py PACK [DUMP...] --out FOLDER
         [--id ID] [--name NAME] [--author AUTHOR] [--rtz FILE] [--hasher PATH]

PACK is the GLideN64 pack: a texture cache (.htc) or a folder of Rice-named PNGs
(<rom name>#<texture crc>#<format>#<size>[#<palette crc>]_all.png, in any subfolder).

GLideN64 names each texture by its Rice hash; RT64 finds replacements by its own. The game's RT64
(recomp/rt64.patch, src/hle/rt64_rice_hash.cpp) works the Rice hash out as each texture is loaded,
so a pack whose rt64.json has the Rice auto path needs nothing else. The game unpacks a .htc put in
its mods folder into such a pack by itself (host/src/gliden64_packs.cpp); this tool makes one to
share, as a folder or a .rtz:

1. it writes the pack's textures to FOLDER as Rice-named PNGs (a .htc is unpacked, a folder copied);
2. without DUMPs, it writes FOLDER/rt64.json with the Rice auto path and no textures listed, and
   every texture goes in the .rtz;
3. with DUMPs, folders of textures RT64 dumped while the game was played (RT64's developer mode,
   "developer_mode": true in graphics.json in the data folder; F1, "Start dumping textures"), it
   runs RT64's texture_hasher --rice on each (built with the game: host/build-win/rt64/src/tools/
   texture_hasher/, or host/build/... on Linux and macOS) and lists the dumped textures the pack
   has a replacement for, each paired with RT64's hash, as RT64 without live matching needs. GLideN64
   leaves the palette out of a texture's name unless it's a CI texture (format 2), but RT64's hasher
   adds it whenever a palette is loaded, which Conker does for some RGBA textures: those are matched
   without it. Only the listed textures go in the .rtz, and the tool reports how many of the pack's
   textures are listed: the rest need more of the game dumped;
4. it writes FOLDER/mod.json, so FOLDER can be put in the mods folder as it is, and with --rtz, a
   .rtz (rt64.json and the textures, zipped) to share.

The .htc format (GLideN64, src/GLideNHQ/TxCache.cpp, TxMemoryCache): a gzip stream of an int32
version (0x08000000; older caches start with the config instead, and have no N64 format and size,
which the names need), an int32 config, then per texture: uint64 checksum (low word the texture's
Rice CRC, high word the palette's), uint32 width and height, uint32 GL format (bit 31: the data is
zlib-compressed), uint16 GL texture format, uint16 GL pixel type, uint8 is_hires, uint16 N64 format
(low byte) and size (high byte), uint32 data size, then the data: RGBA8 pixels in the packs made
from PNGs.
"""

import argparse
import gzip
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTC_VERSION = 0x08000000
GL_TEXFMT_GZ = 0x80000000
GL_UNSIGNED_BYTE = 0x1401
RICE_NAME = re.compile(r'^[^#]*#([0-9a-fA-F]{8})#(\d+)#(\d+)(?:#([0-9a-fA-F]{8}))?_all\.png$')
ROM_NAME = "CONKER BFD"
HASHER_DIRS = ["host/build-win/rt64/src/tools/texture_hasher", "host/build/rt64/src/tools/texture_hasher"]


def rice_key(crc, fmt, siz, palette):
    key = "%08x#%d#%d" % (crc, fmt, siz)
    return key + ("#%08x" % palette if palette else "")


def png_bytes(width, height, rgba):
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def read_exact(f, n):
    data = f.read(n)
    if len(data) != n:
        raise EOFError
    return data


def unpack_htc(path, out):
    """Writes the cache's textures to out as Rice-named PNGs; returns {rice key: file name}."""
    files = {}
    skipped = 0
    with gzip.open(path, "rb") as f:
        version, = struct.unpack("<i", read_exact(f, 4))
        if version != HTC_VERSION:
            sys.exit(f"{path}: an old GLideN64 cache, without the textures' N64 format and size. "
                     "Rebuild it with a current GLideN64, or convert the pack's PNG folder instead.")
        read_exact(f, 4)  # config
        while True:
            try:
                checksum, = struct.unpack("<Q", read_exact(f, 8))
            except EOFError:
                break
            width, height, gl_format, _, pixel_type, _, formatsize, size = struct.unpack(
                "<IIIHHBHI", read_exact(f, 4 + 4 + 4 + 2 + 2 + 1 + 2 + 4))
            data = read_exact(f, size)
            if gl_format & GL_TEXFMT_GZ:
                data = zlib.decompress(data)
            if pixel_type != GL_UNSIGNED_BYTE or len(data) != width * height * 4:
                skipped += 1  # compressed (S3TC) or packed formats
                continue
            crc, palette = checksum & 0xFFFFFFFF, checksum >> 32
            fmt, siz = formatsize & 0xFF, formatsize >> 8
            name = "%s#%08X#%d#%d%s_all.png" % (ROM_NAME, crc, fmt, siz, "#%08X" % palette if palette else "")
            with open(os.path.join(out, name), "wb") as png:
                png.write(png_bytes(width, height, data))
            files[rice_key(crc, fmt, siz, palette)] = name
    if skipped:
        print(f"  {skipped} textures skipped: not stored as RGBA8 (build the cache without texture compression)")
    return files


def copy_png_folder(folder, out):
    files = {}
    for dirpath, _, names in os.walk(folder):
        for name in names:
            m = RICE_NAME.match(name)
            if not m:
                continue
            key = rice_key(int(m.group(1), 16), int(m.group(2)), int(m.group(3)), int(m.group(4), 16) if m.group(4) else 0)
            if key not in files:
                shutil.copyfile(os.path.join(dirpath, name), os.path.join(out, name))
                files[key] = name
    return files


def find_hasher(given):
    if given:
        return given
    exe = "texture_hasher" + (".exe" if os.name == "nt" else "")
    for d in HASHER_DIRS:
        for sub in ["", "Release", "RelWithDebInfo"]:
            path = os.path.join(ROOT, d, sub, exe)
            if os.path.isfile(path):
                return path
    sys.exit("texture_hasher not found: build the game first (it's built with RT64), or pass --hasher.")


def main():
    parser = argparse.ArgumentParser(description="Converts a GLideN64 texture pack to an RT64 one (see the top of this file).")
    parser.add_argument("pack", help="the GLideN64 pack: a .htc file or a folder of Rice-named PNGs")
    parser.add_argument("dumps", nargs="*", help="folders of textures RT64 dumped while playing (optional)")
    parser.add_argument("--out", required=True, help="the RT64 pack's folder (made, or emptied first)")
    parser.add_argument("--id", help="the pack's mod id (default: the folder's name)")
    parser.add_argument("--name", help="the name shown in the Mods menu and the settings")
    parser.add_argument("--author", default="Unknown", help="the pack's author, for mod.json")
    parser.add_argument("--rtz", help="also write the pack as this .rtz file, to share")
    parser.add_argument("--hasher", help="RT64's texture_hasher program")
    args = parser.parse_args()

    out = os.path.abspath(args.out)
    if os.path.isdir(out):
        for name in os.listdir(out):
            if name.lower().endswith(".png") or name in ("rt64.json", "mod.json"):
                os.remove(os.path.join(out, name))
    os.makedirs(out, exist_ok=True)

    print("1. The pack's textures")
    files = unpack_htc(args.pack, out) if os.path.isfile(args.pack) else copy_png_folder(args.pack, out)
    print(f"  {len(files)} textures")

    dumped = {}
    if args.dumps:
        print("2. The dumped textures' Rice hashes")
        hasher = find_hasher(args.hasher)
    for dump in args.dumps:
        result = subprocess.run([hasher, dump, "--rice"], capture_output=True, text=True)
        database = os.path.join(dump, "rt64.json")
        if result.returncode != 0 or not os.path.isfile(database):
            sys.exit(f"texture_hasher failed on {dump}:\n{result.stderr.strip()}")
        for texture in json.load(open(database, encoding="utf-8"))["textures"]:
            dumped[texture["hashes"]["rt64"]] = texture["hashes"]["rice"]
    if args.dumps:
        print(f"  {len(dumped)} textures dumped")
        print("3. Matching them to the pack")
    textures = []
    matched = set()
    for rt64_hash, rice in sorted(dumped.items()):
        parts = rice.split("#")
        if rice not in files and len(parts) == 4 and parts[1] != "2" and "#".join(parts[:3]) in files:
            rice = "#".join(parts[:3])
        if rice in files:
            textures.append({"hashes": {"rt64": rt64_hash, "rice": rice}, "path": ""})
            matched.add(rice)
    database = {
        "configuration": {"autoPath": "rice", "configurationVersion": 3, "hashVersion": 5},
        "textures": textures,
        "operationFilters": [], "shiftFilters": [], "extraFiles": [],
    }
    with open(os.path.join(out, "rt64.json"), "w", encoding="utf-8") as f:
        json.dump(database, f, indent=4)
    if args.dumps:
        print(f"  {len(textures)} dumped textures have a replacement; {len(matched)} of the pack's "
              f"{len(files)} textures are listed, the rest need more of the game dumped")
    else:
        # Matched live by their Rice names: every texture is used.
        matched = set(files)
        print("2. rt64.json: the Rice auto path, for RT64 to match the textures as they're loaded")

    print(("4. " if args.dumps else "3. ") + "mod.json" + (" and " + args.rtz if args.rtz else ""))
    mod_id = args.id or os.path.basename(out)
    manifest = {"game_id": "conker", "id": mod_id, "version": "1.0.0", "display_name": args.name or mod_id,
                "authors": [args.author], "minimum_recomp_version": "0.1.0"}
    with open(os.path.join(out, "mod.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)
    if args.rtz:
        with zipfile.ZipFile(args.rtz, "w", zipfile.ZIP_STORED) as z:
            z.write(os.path.join(out, "rt64.json"), "rt64.json")
            for name in sorted(files[key] for key in matched):
                z.write(os.path.join(out, name), name)
        print(f"  {args.rtz}: {len(matched)} textures")


if __name__ == "__main__":
    main()
