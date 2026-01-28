FF16 Import Debug Pack
======================

This folder contains files to help debug texture linking issues in the FF16 Map Importer.

Contents:
1.  .mtl Files: 5 representative material files (e.g., a_f00_a00_f_0_o.mtl).
2.  .png Files: Textures corresponding to the MTL files.
    - Note: These were found by matching the filename stem (e.g., matching "a_f00_a00_f_0*") because strict path parsing from the MTL binary yielded paths that didn't directly match files on disk (e.g., "base.tex").
3.  Model: 'bt_a01_grou_stonestep02_LOD0' (gltf + bin)
    - This is an example model that appears untextured (purple) in Blender.
4.  Lists:
    - mtl_file_list.txt: Full list of all MTL files in the mtl directory.
    - texture_file_list.txt: Full recursive list of all PNG files in the converted root.
    - console_log.txt: Output log from the importer script showing the "Building MTL database" step.

Configuration Used in Importer (ffxvi_map_importer.py):
- CONVERTED_ROOT = r"G:\16 extract\converted files"
- MPB_PATH = r"G:\16 extract 2\map\t\a01\a00\t_a01_a00.mpb"
- STAGESET_ROOT = r"G:\16 extract 2"

Zone Info:
- Area: a01 (likely surrounding 'stonestep02')
- Issue: Textures exist in the converted folder (as seen in this pack), but the importer fails to link them via the MTL parser.

Debug Script Info:
- We used a python script to parse the MTLs. It found strings like "tBaseColor" (Shader Variable) and "base.tex" (Path?).
- "base.tex" does not exist as a file. The actual file is named like "t_a_f00_a00_f_0_base.png".
- This suggests a mapping logic is missing or the MTL refers to an internal name that needs resolving against the file hash/name.
