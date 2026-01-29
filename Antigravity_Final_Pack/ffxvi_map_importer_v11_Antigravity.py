import bpy
import os
import struct
import math
import mathutils
from pathlib import Path
import re

# --- CONFIGURATION (EDIT THESE) ---
CONVERTED_ROOT = r"G:\16 extract\converted files"
MPB_PATH = r"G:\16 extract 2\map\t\a01\a00\t_a01_a00.mpb"
STAGESET_ROOT = r"G:\16 extract 2"

# Global roots for recursive MTL/Texture scanning (Antigravity v11 Addition)
MTL_GLOBAL_ROOTS = [r"G:\16 extract", r"G:\16 extract 2"]
TEXTURE_ROOTS = [r"G:\16 extract\converted files"]

GLOBAL_SCALE = 0.01

# --- DEBUG OUTPUT ---
def debug_print(msg):
    print(f"[FF16-v11] {msg}")
    import sys
    sys.stdout.flush()

def align(pos, alignment):
    return pos + ((-pos % alignment + alignment) % alignment)

# --- BINARY MTL PARSER (Robust v11 Version) ---
class MtlParser:
    """Parses FF16 proprietary binary .mtl files."""
    def __init__(self):
        self.shader_name = None
        self.texture_paths = []

    def parse(self, mtl_path):
        try:
            with open(mtl_path, 'rb') as f:
                data = f.read()

            if len(data) < 0x24 or data[0:4] != b'MTL ':
                return False

            num_texture_paths = struct.unpack('<H', data[16:18])[0]
            param_section_size = struct.unpack('<I', data[20:24])[0]
            num_constants = struct.unpack('<H', data[24:26])[0]

            header_size = 0x24
            texture_paths_offset = header_size + 4
            
            # Critical 16-byte alignment discovered through forensic hex analysis
            string_table_pos = align(
                texture_paths_offset + num_texture_paths * 8 + num_constants * 8 + param_section_size,
                16
            )

            shader_name_offset = struct.unpack('<I', data[header_size:header_size+4])[0]
            self.shader_name = self._read_string(data, string_table_pos + shader_name_offset)

            self.texture_paths = []
            for i in range(num_texture_paths):
                entry_offset = texture_paths_offset + (i * 8)
                if entry_offset + 8 > len(data): break

                path_off_rel = struct.unpack('<I', data[entry_offset:entry_offset+4])[0]
                name_off_rel = struct.unpack('<I', data[entry_offset+4:entry_offset+8])[0]

                path = self._read_string(data, string_table_pos + path_off_rel)
                shader_var = self._read_string(data, string_table_pos + name_off_rel)

                if path:
                    self.texture_paths.append((shader_var, path))

            return True
        except Exception as e:
            return False

    def _read_string(self, data, offset):
        if offset >= len(data): return ""
        end = data.find(b'\x00', offset)
        if end == -1: end = len(data)
        return data[offset:end].decode('utf-8', errors='ignore')

    def get_texture(self, texture_type):
        """Finds texture by type (base, normal, etc) by scanning shader variables."""
        keywords = {
            'base': ['base', 'color', 'diffuse', 'albedo', 'BaseColor', 'basecolor'],
            'normal': ['normal', 'norm', 'nrm', 'Normal'],
            'rough': ['rough', 'roug', 'Roughness'],
            'metal': ['metal', 'metallic', 'Metallic'],
        }
        type_keywords = keywords.get(texture_type.lower(), [texture_type.lower()])
        for shader_var, path in self.texture_paths:
            var_lower = shader_var.lower()
            if any(kw in var_lower for kw in type_keywords):
                return path
        return None

# --- UNIVERSAL MATERIAL RESOLVER (Antigravity v11 Key Feature) ---
class UniversalMaterialResolver:
    """Uses global recursive indexing to solve modular material mapping."""
    def __init__(self, mtl_roots, texture_roots):
        self.mtl_roots = [Path(root) for root in mtl_roots]
        self.texture_roots = [Path(root) for root in texture_roots]
        self.mtl_cache = {}
        self.texture_cache = {}
        self._index_textures()
        self._index_mtls()

    def _index_textures(self):
        count = 0
        for root in self.texture_roots:
            if not root.exists(): continue
            for tex_file in root.rglob("*.png"):
                stem = tex_file.stem.lower()
                self.texture_cache[stem] = tex_file
                if stem.startswith("t_"):
                    self.texture_cache[stem[2:]] = tex_file
                count += 1
        debug_print(f"Indexed {count} texture files.")

    def _index_mtls(self):
        count = 0
        # Restrict to relevant folders to avoid scanning system files
        scan_subfolders = ['env', 'map', 'common', 'bgparts', 'material', 'mtl files']
        for root in self.mtl_roots:
            if not root.exists(): continue
            for sub in scan_subfolders:
                sub_path = root / sub
                if not sub_path.exists(): continue
                for mtl_file in sub_path.rglob("*.mtl"):
                    parser = MtlParser()
                    if parser.parse(mtl_file):
                        name = mtl_file.stem.lower()
                        if name.startswith('m_'): name = name[2:]
                        self.mtl_cache[name] = parser
                        count += 1
        debug_print(f"Indexed {count} MTL files globally.")

    def resolve(self, material_name):
        """Primary resolution pipe: MTL -> Exact Match -> Keyword Scoring."""
        material_name = material_name.lower()
        if material_name.startswith('m_'): material_name = material_name[2:]

        # 1. THE MTL LINK (Definitive)
        mtl = self.mtl_cache.get(material_name)
        if mtl:
            base_tex = mtl.get_texture('base')
            if base_tex:
                stem = Path(base_tex).stem.lower()
                if stem in self.texture_cache:
                    return {'base': self.texture_cache[stem], 'source': 'MTL-Extract'}

        # 2. EXACT NAME (Fallback)
        suffixes = ['_base', '_diffuse', '_albedo', '_color']
        for s in suffixes:
            key = (material_name + s).lower()
            if key in self.texture_cache:
                return {'base': self.texture_cache[key], 'source': 'Exact-Match'}

        # 3. KEYWORD SCORING (Heuristic Fallback)
        parts = material_name.split('_')
        for part in reversed(parts):
            # Ignore generic engine/zone labels
            if part in ['bt', 'a01', 'b0', 'ba', 'buil', 'reli', 'grou', 'ston', 'wood']: continue
            if part.isdigit(): continue
            
            clean = part.rstrip('0123456789abcdefghijklmnopqrstuvwxyz')
            if not clean: clean = part
            
            for stem, path in self.texture_cache.items():
                if not any(s in stem for s in suffixes): continue
                if f"_{clean}_" in stem or stem.endswith(f"_{clean}"):
                    return {'base': path, 'source': f'Heuristic({clean})'}

        return None

# --- LIGHT ENTITY PARSER (Type 2001) ---
class LightEntityParser:
    @staticmethod
    def parse_light(entity_data, abs_off):
        l_off = abs_off + 0x50
        if l_off + 0x40 > len(entity_data): return None
        
        try:
            l_type = struct.unpack('<i', entity_data[l_off : l_off+4])[0]
            color_u = struct.unpack('<I', entity_data[l_off+4 : l_off+8])[0]
            # Normalization ARGB
            r = ((color_u >> 16) & 0xFF) / 255.0
            g = ((color_u >> 8) & 0xFF) / 255.0
            b = (color_u & 0xFF) / 255.0
            
            intensity = struct.unpack('<f', entity_data[l_off+20 : l_off+24])[0] * 100
            range_val = struct.unpack('<f', entity_data[l_off+28 : l_off+32])[0] * GLOBAL_SCALE
            
            return {
                'type': 'POINT' if l_type == 0 else 'SPOT',
                'color': (r, g, b),
                'energy': intensity,
                'range': range_val
            }
        except: return None

# --- ASSET LOCATOR (GLTF/MDL) ---
class AssetLocator:
    def __init__(self, root):
        self.root = Path(root)
        self.gltf_index = {}
        if self.root.exists():
            for f in self.root.rglob("*.gltf"):
                self.gltf_index[f.stem.lower()] = f
        debug_print(f"Located {len(self.gltf_index)} GLTF models.")

    def find(self, rel_path):
        if not rel_path: return None
        stem = Path(rel_path).stem.lower()
        cands = [stem, f"{stem}_lod0", f"{stem}_0"]
        for c in cands:
            if c in self.gltf_index: return self.gltf_index[c]
        return None

# --- MPB PARSER ---
class MpbParser:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f: self.data = f.read()

    def _read_str(self, off):
        end = self.data.find(b'\x00', off)
        return self.data[off:end].decode('utf-8', errors='ignore') if end != -1 else ""

    def parse(self):
        group_list_off = struct.unpack('<I', self.data[4:8])[0]
        group_list_count = struct.unpack('<I', self.data[8:12])[0]
        entities = []
        groups = {}
        for i in range(group_list_count):
            ioff = group_list_off + (i * 0x30)
            eg_rel, eg_count = struct.unpack('<II', self.data[ioff+0x28 : ioff+0x30])
            base_eg = ioff + eg_rel
            for j in range(eg_count):
                eg_ptr = base_eg + (j * 0x3C)
                gid = struct.unpack('<i', self.data[eg_ptr+4:eg_ptr+8])[0]
                groups[gid] = {'id': gid}
                ent_rel, ent_count = struct.unpack('<II', self.data[eg_ptr+0x10 : eg_ptr+0x18])
                base_ent = eg_ptr + ent_rel
                for k in range(ent_count):
                    off_ptr = base_ent + (k * 4)
                    rel = struct.unpack('<i', self.data[off_ptr:off_ptr+4])[0]
                    abs_off = base_ent + rel
                    etype = struct.unpack('<I', self.data[abs_off+4:abs_off+8])[0]
                    px, py, pz = struct.unpack('<3d', self.data[abs_off+0x10 : abs_off+0x28])
                    rx, ry, rz = struct.unpack('<3f', self.data[abs_off+0x28 : abs_off+0x34])
                    s = struct.unpack('<f', self.data[abs_off+0x34 : abs_off+0x38])[0]
                    pgid = struct.unpack('<i', self.data[abs_off+0x0C : abs_off+0x10])[0]
                    path = ""
                    if etype in [1015, 1028, 5001]:
                        poff = struct.unpack('<i', self.data[abs_off+0x54 : abs_off+0x58])[0]
                        path = self._read_str(abs_off + 0x50 + poff)
                    entities.append({
                        'type': etype, 'path': path, 'pos': (px, py, pz),
                        'rot': (rx, ry, rz), 'scl': (s,s,s), 'pgid': pgid, 'abs_off': abs_off
                    })
        return entities, list(groups.values())

# --- BLENDER TOOLS ---
def apply_materials_to_obj(obj, resolver):
    if not obj.data or not obj.data.materials: return
    for mat in obj.data.materials:
        if not mat: continue
        res = resolver.resolve(mat.name)
        if not res: continue
        
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf: continue
        
        tex_path = str(res['base'])
        img_name = Path(tex_path).name
        if img_name not in bpy.data.images:
            img = bpy.data.images.load(tex_path)
        else:
            img = bpy.data.images[img_name]
            
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = img
        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
        debug_print(f"  Linked {img_name} to {mat.name} via {res['source']}")

def run_import():
    debug_print("Starting FF16 v11 Map Importer...")
    resolver = UniversalMaterialResolver(MTL_GLOBAL_ROOTS, TEXTURE_ROOTS)
    locator = AssetLocator(CONVERTED_ROOT)
    parser = MpbParser(MPB_PATH)
    entities, groups_info = parser.parse()
    
    # 1. SPATIAL DEDUPLICATION (v11 Patch) - Prevents wall-stalling arches
    buckets = {}
    final_entities = []
    for ent in entities:
        if not ent['path'] and ent['type'] != 2001: 
            final_entities.append(ent)
            continue
        # Hash by location to fine redundant state-variants
        h = (round(ent['pos'][0], 1), round(ent['pos'][1], 1), round(ent['pos'][2], 1))
        if h not in buckets:
            buckets[h] = True
            final_entities.append(ent)
        else:
            pass # Skip redundant overlap
            
    debug_print(f"Deduplicated scene: {len(final_entities)}/{len(entities)} entities kept.")

    # 2. CREATE GROUP HIERARCHY
    group_map = {}
    for g in groups_info:
        g_mt = bpy.data.objects.new(f"GRP_{g['id']}", None)
        bpy.context.collection.objects.link(g_mt)
        group_map[g['id']] = g_mt

    # 3. IMPORT LOOP
    global_cache = {}
    for ent in final_entities:
        name = Path(ent['path']).stem if ent['path'] else f"Type_{ent['type']}"
        parent_mt = group_map.get(ent['pgid'])
        
        obj = None
        if ent['type'] == 1028 and ent['path'].endswith('.mdl'):
            gltf = locator.find(ent['path'])
            if gltf:
                if gltf in global_cache:
                    # Instancing
                    obj = global_cache[gltf].copy()
                    bpy.context.collection.objects.link(obj)
                else:
                    try:
                        bpy.ops.import_scene.gltf(filepath=str(gltf))
                        imported = bpy.context.selected_objects
                        obj = bpy.data.objects.new(name, None)
                        for io in imported:
                            if io.parent is None: io.parent = obj
                            apply_materials_to_obj(io, resolver)
                        global_cache[gltf] = obj
                    except: pass
        elif ent['type'] == 2001: # Lights
            l_info = LightEntityParser.parse_light(parser.data, ent['abs_off'])
            if l_info:
                l_data = bpy.data.lights.new(name=f"LGT_{name}", type=l_info['type'])
                l_data.color = l_info['color']
                l_data.energy = l_info['energy']
                obj = bpy.data.objects.new(name=f"LGT_{name}", object_data=l_data)
        
        if not obj: obj = bpy.data.objects.new(name, None)
        
        bpy.context.collection.objects.link(obj)
        obj.parent = parent_mt
        # Coordinate Correction (Game to Blender)
        obj.location = (ent['pos'][0], -ent['pos'][2], ent['pos'][1])
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = (ent['rot'][0], -ent['rot'][2], ent['rot'][1])
        obj.scale = ent['scl']

    debug_print("Import Done!")

if __name__ == "__main__":
    run_import()
