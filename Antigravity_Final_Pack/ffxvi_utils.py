import os
import struct
from pathlib import Path

# --- UTILS ---
def read_string(data, offset):
    if offset >= len(data): return ""
    end = data.find(b'\x00', offset)
    if end == -1: end = len(data)
    return data[offset:end].decode('utf-8', errors='ignore')

def align(pos, alignment):
    return pos + ((-pos % alignment + alignment) % alignment)

# --- MTL PARSER ---
class MtlParser:
    def __init__(self):
        self.shader_name = None
        self.texture_paths = []

    def parse(self, mtl_path):
        try:
            with open(mtl_path, 'rb') as f:
                data = f.read()
            if len(data) < 0x24 or data[0:4] != b'MTL ': return False

            num_texture_paths = struct.unpack('<H', data[16:18])[0]
            param_section_size = struct.unpack('<I', data[20:24])[0]
            num_constants = struct.unpack('<H', data[24:26])[0]

            header_size = 0x24
            texture_paths_offset = header_size + 4
            string_table_pos = align(
                texture_paths_offset + num_texture_paths * 8 + num_constants * 8 + param_section_size,
                16
            )

            shader_name_offset = struct.unpack('<I', data[header_size:header_size+4])[0]
            self.shader_name = read_string(data, string_table_pos + shader_name_offset)

            self.texture_paths = []
            for i in range(num_texture_paths):
                entry_offset = texture_paths_offset + (i * 8)
                path_off = struct.unpack('<I', data[entry_offset:entry_offset+4])[0]
                name_off = struct.unpack('<I', data[entry_offset+4:entry_offset+8])[0]
                tex_path = read_string(data, string_table_pos + path_off)
                shader_var = read_string(data, string_table_pos + name_off)
                if tex_path:
                    self.texture_paths.append((shader_var, tex_path))
            return True
        except: return False

    def get_texture(self, texture_type):
        keywords = {
            'base': ['base', 'color', 'diffuse', 'albedo', 'BaseColor', 'basecolor'],
            'normal': ['normal', 'norm', 'nrm', 'Normal'],
        }
        type_keywords = keywords.get(texture_type.lower(), [texture_type.lower()])
        for shader_var, path in self.texture_paths:
            var_lower = shader_var.lower()
            for kw in type_keywords:
                if kw in var_lower: return path
        return None

# --- RESOLVER ---
class UniversalMaterialResolver:
    def __init__(self, mtl_roots, texture_roots):
        self.mtl_roots = [Path(p) for p in mtl_roots]
        self.texture_roots = [Path(p) for p in texture_roots]
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

    def _index_mtls(self):
        count = 0
        for root in self.mtl_roots:
            if not root.exists(): continue
            # Only scan relevant subfolders to save time
            for sub in ['env', 'map', 'mtl files']:
                sub_path = root / sub
                if not sub_path.exists(): continue
                for mtl_file in sub_path.rglob("*.mtl"):
                    p = MtlParser()
                    if p.parse(mtl_file):
                        name = mtl_file.stem.lower()
                        if name.startswith('m_'): name = name[2:]
                        self.mtl_cache[name] = p
                        count += 1

    def resolve(self, material_name):
        material_name = material_name.lower()
        if material_name.startswith('m_'): material_name = material_name[2:]
        
        mtl = self.mtl_cache.get(material_name)
        if mtl:
            base_tex = mtl.get_texture('base')
            if base_tex:
                stem = Path(base_tex).stem.lower()
                if stem in self.texture_cache:
                    return {'base': self.texture_cache[stem], 'source': 'MTL'}

        for suf in ['_base', '_diffuse', '_albedo', '_color']:
            key = (material_name + suf).lower()
            if key in self.texture_cache:
                return {'base': self.texture_cache[key], 'source': 'Exact'}

        parts = material_name.split('_')
        for part in reversed(parts):
            if part in ['a01', 'b0', 'ba', 'bt', 'buil', 'debr', 'grou', 'ston', 'wood', 'reli']: continue
            if part.isdigit(): continue
            clean = part.rstrip('0123456789abcdefghijklmnopqrstuvwxyz')
            if not clean: clean = part
            for stem, path in self.texture_cache.items():
                if not stem.endswith(('_base', '_diffuse', '_albedo', '_color')): continue
                if f"_{clean}_" in stem or stem.endswith(f"_{clean}"):
                    return {'base': path, 'source': f'Keyword({clean})'}
        return None
