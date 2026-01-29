import bpy
import os
import struct
import math
import mathutils
from pathlib import Path
from ffxvi_utils import UniversalMaterialResolver, MtlParser

# --- CONFIGURATION (v12 DEFINITIVE) ---
CONVERTED_ROOT = r"G:\16 extract\converted files"
MPB_PATH = r"G:\16 extract 2\map\t\a01\a00\t_a01_a00.mpb"
STAGESET_ROOT = r"G:\16 extract 2"

# Multi-root scanning (Antigravity v11/v12 discovery)
MTL_GLOBAL_ROOTS = [r"G:\16 extract", r"G:\16 extract 2"]
TEXTURE_ROOTS = [r"G:\16 extract\converted files"]

# Feature Toggles
ENABLE_SPATIAL_DEDUPLICATION = True
DEDUPLICATION_TOLERANCE = 0.01  # Kimi v12 suggestion: higher precision
GLOBAL_SCALE = 0.01

# --- LOGGING ---
def debug_print(msg):
    print(f"[FF16-v12] {msg}")
    import sys
    sys.stdout.flush()

# --- LIGHT PARSER ---
class LightEntityParser:
    @staticmethod
    def parse_light(entity_data, abs_off):
        l_off = abs_off + 0x50
        if l_off + 0x40 > len(entity_data): return None
        try:
            l_raw_type = struct.unpack('<i', entity_data[l_off : l_off+4])[0]
            color_u = struct.unpack('<I', entity_data[l_off+4 : l_off+8])[0]
            # Normalization ARGB -> RGB
            r = ((color_u >> 16) & 0xFF) / 255.0
            g = ((color_u >> 8) & 0xFF) / 255.0
            b = (color_u & 0xFF) / 255.0
            
            intensity = struct.unpack('<f', entity_data[l_off+20 : l_off+24])[0] * 100
            range_val = struct.unpack('<f', entity_data[l_off+28 : l_off+32])[0] * GLOBAL_SCALE
            
            return {
                'type': 'POINT' if l_raw_type == 0 else 'SPOT',
                'color': (r, g, b),
                'energy': intensity,
                'range': range_val
            }
        except: return None

# --- ASSET LOCATOR ---
class AssetLocator:
    def __init__(self, root):
        self.root = Path(root)
        self.gltf_index = {}
        if self.root.exists():
            debug_print(f"Indexing models in {root}...")
            for f in self.root.rglob("*.gltf"):
                self.gltf_index[f.stem.lower()] = f
        debug_print(f"Located {len(self.gltf_index)} GLTF models.")

    def find(self, rel_path):
        if not rel_path: return None
        stem = Path(rel_path).stem.lower()
        # Handle common LOD suffixes
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
def apply_materials(obj, resolver):
    if not obj.data or not hasattr(obj.data, 'materials'): return
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
        debug_print(f"    [Material] Linked {img_name} to {mat.name} ({res['source']})")

def run_import():
    debug_print("FF16 Importer v12 - Definitive Edition")
    
    # Initialize Core Engines
    resolver = UniversalMaterialResolver(MTL_GLOBAL_ROOTS, TEXTURE_ROOTS)
    locator = AssetLocator(CONVERTED_ROOT)
    parser = MpbParser(MPB_PATH)
    entities, groups_info = parser.parse()
    
    # 1. REFINED SPATIAL DEDUPLICATION (v12)
    final_entities = []
    if ENABLE_SPATIAL_DEDUPLICATION:
        buckets = {}
        for ent in entities:
            if not ent['path'] and ent['type'] != 2001: 
                final_entities.append(ent)
                continue
            
            # Use high precision hash (0.01m) as per Kimi suggestion
            h = (round(ent['pos'][0], 2), round(ent['pos'][1], 2), round(ent['pos'][2], 2))
            # Include path in hash to avoid removing different models at same spot
            path_hash = ent['path'].lower()
            full_key = (h, path_hash)
            
            if full_key not in buckets:
                buckets[full_key] = True
                final_entities.append(ent)
            else:
                pass # Redundant state-variant skipped
        debug_print(f"Deduplication: Reduced {len(entities)} to {len(final_entities)} entities.")
    else:
        final_entities = entities

    # 2. CREATE LOGICAL HIERARCHY
    group_map = {}
    for g in groups_info:
        g_mt = bpy.data.objects.new(f"GRP_{g['id']}", None)
        bpy.context.collection.objects.link(g_mt)
        group_map[g['id']] = g_mt

    # 3. GLOBAL ASSET CACHE (Instancing Support)
    global_cache = {}

    # 4. MAIN IMPORT LOOP
    for idx, ent in enumerate(final_entities):
        asset_name = Path(ent['path']).stem if ent['path'] else f"ID_{ent['abs_off']:X}"
        parent_empty = group_map.get(ent['pgid'])
        
        # Create Entity Empty (Carrier)
        ent_obj = bpy.data.objects.new(f"ENT_{asset_name}", None)
        bpy.context.collection.objects.link(ent_obj)
        ent_obj.parent = parent_empty
        
        # Apply World Transform (Verified v10/v11 Matrix)
        ent_obj.location = (ent['pos'][0], -ent['pos'][2], ent['pos'][1])
        ent_obj.rotation_mode = 'XYZ'
        ent_obj.rotation_euler = (ent['rot'][0], -ent['rot'][2], ent['rot'][1])
        ent_obj.scale = ent['scl']
        
        # Import Payload
        if ent['type'] == 1028 and ent['path'].endswith('.mdl'):
            gltf_file = locator.find(ent['path'])
            if gltf_file:
                if gltf_file in global_cache:
                    # Logic for instanced meshes
                    mesh_instance = global_cache[gltf_file].copy()
                    bpy.context.collection.objects.link(mesh_instance)
                    mesh_instance.parent = ent_obj
                    mesh_instance.location = (0,0,0)
                    mesh_instance.rotation_euler = (0,0,0)
                else:
                    try:
                        bpy.ops.import_scene.gltf(filepath=str(gltf_file))
                        imported = bpy.context.selected_objects
                        # Kimi v12 Suggestion: Direct parenting to entity empty
                        for io in imported:
                            if io.parent is None:
                                io.parent = ent_obj
                                io.location = (0,0,0)
                                io.rotation_euler = (0,0,0)
                            apply_materials(io, resolver)
                        # Cache first root for instancing
                        for io in imported:
                            if io.parent == ent_obj:
                                global_cache[gltf_file] = io
                                break
                    except Exception as e:
                        debug_print(f"  [Error] Failed to import GLTF {asset_name}: {e}")
            else:
                debug_print(f"  [Warning] Model not found on disk: {ent['path']}")
                
        elif ent['type'] == 2001: # Dynamic Lights
            l_info = LightEntityParser.parse_light(parser.data, ent['abs_off'])
            if l_info:
                l_data = bpy.data.lights.new(name=f"DATA_{asset_name}", type=l_info['type'])
                l_data.color = l_info['color']
                l_data.energy = l_info['energy']
                l_obj = bpy.data.objects.new(f"LGT_{asset_name}", object_data=l_data)
                bpy.context.collection.objects.link(l_obj)
                l_obj.parent = ent_obj
                debug_print(f"  [Light] Injected {l_info['type']} into {asset_name}")

    debug_print("FF16 v12 Import Complete. Check Blender Outliner.")

if __name__ == "__main__":
    run_import()
