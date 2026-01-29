import os
import struct
from pathlib import Path
import re

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
            'rough': ['rough', 'roug', 'Roughness'],
            'metal': ['metal', 'metallic', 'Metallic'],
        }
        type_keywords = keywords.get(texture_type.lower(), [texture_type.lower()])
        for shader_var, path in self.texture_paths:
            var_lower = shader_var.lower()
            if any(kw in var_lower for kw in type_keywords):
                return path
        return None

# --- RESOLVER ---
class UniversalMaterialResolver:
    def __init__(self, mtl_roots, texture_roots):
        self.mtl_roots = [Path(p) for p in mtl_roots]
        self.texture_roots = [Path(p) for p in texture_roots]
        self.mtl_cache = {}
        self.texture_cache = {}
        # New for v12: Score-based identifier extraction
        self.generic_prefixes = ['bt', 'ba', 'm', 't']
        self.generic_categories = ['reli', 'buil', 'grou', 'ston', 'wood', 'debr', 'acce', 'common', 'module']
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
        print(f"[FF16-v12] Indexed {count} textures.")

    def _index_mtls(self):
        count = 0
        blacklist = {
            'converted files', 'sound', 'movie', 'ui', 'vfx', 'chara', 
            'animation', 'cut', 'shader', '__pycache__', '.gemini', 'ghidra',
            'nxd', 'final fantasy 16', 'tb'
        }
        for root in self.mtl_roots:
            if not root.exists(): continue
            print(f"[FF16-v12] Scanning MTLs in {root} (Skipping non-asset folders)...")
            
            # Use os.walk for better control over recursion and skipping
            for dirpath, dirnames, filenames in os.walk(root):
                # Filter dirnames in-place to avoid descending into blacklisted folders
                dirnames[:] = [d for d in dirnames if d.lower() not in blacklist]
                
                for filename in filenames:
                    if filename.lower().endswith('.mtl'):
                        mtl_path = Path(dirpath) / filename
                        p = MtlParser()
                        if p.parse(mtl_path):
                            name = mtl_path.stem.lower()
                            if name.startswith('m_'): name = name[2:]
                            self.mtl_cache[name] = p
                            count += 1
        print(f"[FF16-v12] Indexed {count} MTL files.")

    def _extract_specific_identifier(self, name):
        """Kimi v12 Logic: Strip generic tokens to find the actual core asset name."""
        name = name.lower()
        parts = name.split('_')
        # Skip generic prefixes and categories
        filtered = [p for p in parts if p not in self.generic_prefixes and p not in self.generic_categories and not p.startswith('a01')]
        # Filter out purely numeric parts or zone codes
        filtered = [p for p in filtered if not p.isdigit() and len(p) > 2]
        
        if not filtered: return name
        # Return the last significant token (likely the specific object name)
        return filtered[-1]

    def resolve(self, material_name):
        material_name = material_name.lower()
        if material_name.startswith('m_'): material_name = material_name[2:]
        
        # 1. MTL LINK (Definitive)
        mtl = self.mtl_cache.get(material_name)
        if mtl:
            base_tex = mtl.get_texture('base')
            if base_tex:
                stem = Path(base_tex).stem.lower()
                if stem in self.texture_cache:
                    return {'base': self.texture_cache[stem], 'source': 'MTL-Extract'}

        # 2. EXACT NAME
        suffixes = ['_base', '_diffuse', '_albedo', '_color']
        for suf in suffixes:
            key = (material_name + suf).lower()
            if key in self.texture_cache:
                return {'base': self.texture_cache[key], 'source': 'Exact-Match'}

        # 3. IDENTIFIER SCORING (v12 Enhancement)
        identifier = self._extract_specific_identifier(material_name)
        # Also keep technical suffix (like 'step' or 'wall') for cross-material matching
        parts = material_name.split('_')
        technical_type = parts[-1].rstrip('0123456789') if len(parts) > 1 else ""

        candidates = []
        for stem, path in self.texture_cache.items():
            if not any(s in stem for s in suffixes): continue
            
            score = 0
            # Primary: Identity match (e.g. "crackwall")
            if f"_{identifier}_" in stem or stem.endswith(f"_{identifier}"):
                score += 60
            elif identifier in stem:
                score += 30
            
            # Secondary: Technical type match (e.g. "step" or "wall")
            if technical_type and len(technical_type) > 3:
                if f"_{technical_type}" in stem:
                    score += 20
            
            # Penalty for generic zone mismatches if we have a specific name
            if any(f"_{cat}_" in stem for cat in self.generic_categories if cat != technical_type):
                score -= 10
            
            if score > 20: # Threshold for inclusion
                candidates.append((score, path))
        
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return {'base': candidates[0][1], 'source': f'v12-Scoring({identifier})'}
            
        return None
