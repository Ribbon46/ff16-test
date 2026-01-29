import bpy
import os
import struct
import math
import mathutils
from pathlib import Path

# --- CONFIGURATION ---
CONVERTED_ROOT = r"G:\16 extract\converted files"
MPB_PATH = r"G:\16 extract 2\map\t\a01\a00\t_a01_a00.mpb"
STAGESET_ROOT = r"G:\16 extract 2" 
GLOBAL_SCALE = 0.01

# --- DEBUG OUTPUT ---
def debug_print(msg):
    print(f"[FF16Import] {msg}")
    import sys
    sys.stdout.flush()


class MtlParser:
    """Parses FF16 binary .mtl files to extract texture paths."""

    def __init__(self):
        self.texture_paths = []

    def parse(self, mtl_path):
        try:
            with open(mtl_path, 'rb') as f:
                data = f.read()

            if len(data) < 0x20:
                return False

            if data[0:4] != b'MTL ':
                return False

            num_texture_paths = struct.unpack('<H', data[16:18])[0]
            constant_buffer_size = struct.unpack('<I', data[20:24])[0]
            num_constants = struct.unpack('<H', data[24:26])[0]

            header_size = 0x20
            texture_paths_size = num_texture_paths * 8
            constants_size = num_constants * 8

            string_table_pos = header_size + texture_paths_size + constants_size + constant_buffer_size
            string_table_pos = (string_table_pos + 15) & ~15

            self.texture_paths = []
            for i in range(num_texture_paths):
                entry_offset = header_size + (i * 8)
                if entry_offset + 8 > len(data):
                    break

                path_offset_rel = struct.unpack('<H', data[entry_offset:entry_offset+2])[0]
                shader_var_offset_rel = struct.unpack('<H', data[entry_offset+4:entry_offset+6])[0]

                path = self._read_string(data, string_table_pos + path_offset_rel)
                shader_var = self._read_string(data, string_table_pos + shader_var_offset_rel)

                if path:
                    self.texture_paths.append((shader_var, path))

            return True
        except Exception as e:
            return False

    def _read_string(self, data, offset):
        if offset >= len(data):
            return ""
        end = data.find(b'\x00', offset)
        if end == -1:
            end = len(data)
        return data[offset:end].decode('utf-8', errors='ignore')

    def get_base_color_texture(self):
        for shader_var, path in self.texture_paths:
            var_lower = shader_var.lower()
            if 'base' in var_lower or 'color' in var_lower or 'diffuse' in var_lower:
                return path
        return self.texture_paths[0][1] if self.texture_paths else None

    def get_normal_texture(self):
        for shader_var, path in self.texture_paths:
            var_lower = shader_var.lower()
            if 'normal' in var_lower or 'norm' in var_lower:
                return path
        return None


class FF16MaterialResolver:
    """Enhanced material resolver that reads actual MTL files for texture references."""

    def __init__(self, texture_root, mtl_root):
        self.texture_root = Path(texture_root)
        self.mtl_root = Path(mtl_root)
        self.texture_cache = {}
        self.mtl_cache = {}
        self._build_texture_cache()

    def _build_texture_cache(self):
        if not self.texture_root.exists():
            debug_print(f"WARNING: Texture root not found: {self.texture_root}")
            return

        count = 0
        for tex_file in self.texture_root.rglob("*.png"):
            stem = tex_file.stem.lower()
            self.texture_cache[stem] = tex_file
            if stem.startswith("t_"):
                self.texture_cache[stem[2:]] = tex_file
            for suffix in ['_base', '_diffuse', '_albedo', '_color', '_norm', '_normal', '_nrm', 
                          '_rough', '_roughness', '_roug', '_metal', '_metallic', '_heig', '_height']:
                if stem.endswith(suffix):
                    base_name = stem[:-len(suffix)]
                    self.texture_cache[base_name] = tex_file
                    if base_name.startswith("t_"):
                        self.texture_cache[base_name[2:]] = tex_file
                    break
            count += 1

        debug_print(f"Indexed {count} textures ({len(self.texture_cache)} lookup keys)")

    def _find_mtl_file(self, model_name):
        for gltf_file in self.mtl_root.rglob("*.gltf"):
            gltf_dir = gltf_file.parent
            for name in [model_name, model_name.replace('_LOD0', '').replace('_lod0', '')]:
                mtl_path = gltf_dir / f"{name}.mtl"
                if mtl_path.exists():
                    return mtl_path
                mtl_path = gltf_dir / f"t_{name}.mtl"
                if mtl_path.exists():
                    return mtl_path
        return None

    def _resolve_texture_path(self, mtl_texture_path):
        path_parts = mtl_texture_path.replace('\\', '/').split('/')
        base_name = path_parts[-1].lower() if path_parts else mtl_texture_path.lower()

        if base_name in self.texture_cache:
            return self.texture_cache[base_name]
        if f"t_{base_name}" in self.texture_cache:
            return self.texture_cache[f"t_{base_name}"]
        for suffix in ['_base', '_diffuse', '_albedo', '_color']:
            key = f"{base_name}{suffix}"
            if key in self.texture_cache:
                return self.texture_cache[key]
            key = f"t_{base_name}{suffix}"
            if key in self.texture_cache:
                return self.texture_cache[key]
        return None

    def relink_materials(self, obj, expected_model_name=None):
        if obj.type != 'MESH' or not obj.data.materials:
            return

        for mat in obj.data.materials:
            if not mat:
                continue

            if not mat.use_nodes:
                mat.use_nodes = True

            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            bsdf = None
            for node in nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    bsdf = node
                    break

            if not bsdf:
                continue

            for link in list(links):
                if link.to_socket.name == 'Base Color':
                    if link.from_node.type == 'ATTRIBUTE':
                        links.remove(link)
                    break

            model_name = expected_model_name if expected_model_name else mat.name
            model_name = model_name.lower()
            if model_name.startswith("t_"):
                model_name = model_name[2:]

            debug_print(f"  [Texture] Processing material for '{model_name}'")

            mtl_path = self._find_mtl_file(model_name)
            base_color_path = None
            normal_path = None

            if mtl_path and mtl_path.exists():
                debug_print(f"  [MTL] Found: {mtl_path.name}")
                mtl_parser = MtlParser()
                if mtl_parser.parse(mtl_path):
                    mtl_texture = mtl_parser.get_base_color_texture()
                    normal_texture = mtl_parser.get_normal_texture()
                    if mtl_texture:
                        debug_print(f"  [MTL] Base texture from MTL: {mtl_texture}")
                        base_color_path = self._resolve_texture_path(mtl_texture)
                    if normal_texture:
                        normal_path = self._resolve_texture_path(normal_texture)

            if not base_color_path:
                lookup_keys = [f"t_{model_name}_base", f"t_{model_name}_diffuse", 
                              f"t_{model_name}_albedo", model_name, f"{model_name}_base"]
                for key in lookup_keys:
                    if key in self.texture_cache:
                        base_color_path = self.texture_cache[key]
                        break

            if base_color_path and base_color_path.exists():
                try:
                    img_node = nodes.new('ShaderNodeTexImage')
                    img_node.location = (bsdf.location.x - 300, bsdf.location.y)
                    if base_color_path.name not in bpy.data.images:
                        img = bpy.data.images.load(str(base_color_path))
                    else:
                        img = bpy.data.images[base_color_path.name]
                    img_node.image = img
                    img_node.name = f"Texture_{model_name}"
                    links.new(img_node.outputs['Color'], bsdf.inputs['Base Color'])
                    debug_print(f"  [Success] Linked base color: {base_color_path.name}")
                except Exception as e:
                    debug_print(f"  [Error] Failed to link base color: {e}")

            if not normal_path:
                for key in [f"t_{model_name}_normal", f"t_{model_name}_norm", f"{model_name}_normal"]:
                    if key in self.texture_cache:
                        normal_path = self.texture_cache[key]
                        break

            if normal_path and normal_path.exists():
                try:
                    if normal_path.name not in bpy.data.images:
                        img = bpy.data.images.load(str(normal_path))
                    else:
                        img = bpy.data.images[normal_path.name]
                    tex_node = nodes.new('ShaderNodeTexImage')
                    tex_node.image = img
                    tex_node.name = f"Normal_{model_name}"
                    tex_node.location = (bsdf.location.x - 600, bsdf.location.y - 250)
                    norm_node = nodes.new('ShaderNodeNormalMap')
                    norm_node.location = (bsdf.location.x - 300, bsdf.location.y - 250)
                    links.new(tex_node.outputs['Color'], norm_node.inputs['Color'])
                    links.new(norm_node.outputs['Normal'], bsdf.inputs['Normal'])
                    debug_print(f"  [Success] Linked normal map: {normal_path.name}")
                except Exception as e:
                    debug_print(f"  [Error] Normal map link failed: {e}")


class AssetLocator:
    def __init__(self, converted_root):
        self.root = Path(converted_root)
        self.cache = {}
        self.gltf_index = {}
        self._index_files()

    def _index_files(self):
        if not self.root.exists():
            debug_print(f"CRITICAL ERROR: Converted root does not exist: {self.root}")
            return
        for gltf_file in self.root.rglob("*.gltf"):
            self.gltf_index[gltf_file.stem.lower()] = gltf_file
        debug_print(f"Indexed {len(self.gltf_index)} GLTF files")

    def find_mdl_gltf(self, mdl_path):
        if not mdl_path or not isinstance(mdl_path, str):
            return None
        mdl_path = mdl_path.replace('\\', '/').lower()
        if mdl_path in self.cache:
            return self.cache[mdl_path]
        basename = Path(mdl_path).stem.lower()
        for cand in [basename, f"{basename}_lod0", f"{basename}_0"]:
            if cand in self.gltf_index:
                result = self.gltf_index[cand]
                self.cache[mdl_path] = result
                return result
        return None


class LightEntityParser:
    """Parses FF16 light entity data (Type 2001) from MPB files."""

    # Light type mapping based on FF16 engine
    LIGHT_TYPES = {
        0: 'POINT',
        1: 'SPOT', 
        2: 'SUN',
        3: 'AREA'
    }

    @staticmethod
    def parse_light_data(entity_data, base_offset):
        """
        Parse light-specific data from entity.
        Structure based on FF16_mpb_MapBinary.bt template.
        """
        try:
            # Light data starts after base entity header (0x50 bytes)
            light_offset = base_offset + 0x50

            if light_offset + 0x40 > len(entity_data):
                return None

            # Read light structure
            light_type = struct.unpack('<i', entity_data[light_offset:light_offset+4])[0]
            color_maybe = struct.unpack('<I', entity_data[light_offset+4:light_offset+8])[0]
            field_08 = struct.unpack('<i', entity_data[light_offset+8:light_offset+12])[0]
            field_0C = struct.unpack('<f', entity_data[light_offset+12:light_offset+16])[0]
            field_10 = struct.unpack('<i', entity_data[light_offset+16:light_offset+20])[0]

            # Multiple float fields - likely intensity, range, attenuation
            float_14 = struct.unpack('<f', entity_data[light_offset+20:light_offset+24])[0]
            float_18 = struct.unpack('<f', entity_data[light_offset+24:light_offset+28])[0]
            float_1C = struct.unpack('<f', entity_data[light_offset+28:light_offset+32])[0]
            float_20 = struct.unpack('<f', entity_data[light_offset+32:light_offset+36])[0]

            field_24 = struct.unpack('<i', entity_data[light_offset+36:light_offset+40])[0]
            float_28 = struct.unpack('<f', entity_data[light_offset+40:light_offset+44])[0]
            float_2C = struct.unpack('<f', entity_data[light_offset+44:light_offset+48])[0]

            field_30 = struct.unpack('<i', entity_data[light_offset+48:light_offset+52])[0]
            light_shaking_param_id = struct.unpack('<i', entity_data[light_offset+52:light_offset+56])[0]

            # Decode color (ARGB format commonly used in games)
            # Color is often stored as 0xAARRGGBB or 0xRRGGBBAA
            a = (color_maybe >> 24) & 0xFF
            r = (color_maybe >> 16) & 0xFF
            g = (color_maybe >> 8) & 0xFF
            b = color_maybe & 0xFF

            # If alpha is 0 or 255, try different byte order
            if a == 0 or a == 255:
                # Try RGBA order
                r = (color_maybe >> 24) & 0xFF
                g = (color_maybe >> 16) & 0xFF
                b = (color_maybe >> 8) & 0xFF
                a = color_maybe & 0xFF

            # Normalize to 0-1 range
            color = (r / 255.0, g / 255.0, b / 255.0, a / 255.0)

            # Determine light type
            blender_light_type = LightEntityParser.LIGHT_TYPES.get(light_type, 'POINT')

            # Estimate intensity and range from float fields
            # In FF16, these are likely in game units
            intensity = max(float_14, float_18, 1.0) * 100  # Scale to Blender units
            range_val = max(float_1C, float_20, 10.0) * GLOBAL_SCALE

            return {
                'light_type': blender_light_type,
                'color': color[:3],  # RGB only for Blender
                'intensity': intensity,
                'range': range_val,
                'raw_type': light_type,
                'raw_color': color_maybe,
                'floats': [float_14, float_18, float_1C, float_20, float_28, float_2C],
                'shaking_param_id': light_shaking_param_id
            }

        except Exception as e:
            debug_print(f"  [Light] Parse error: {e}")
            return None


class MpbParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = None
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                self.data = f.read()
            debug_print(f"Loaded MPB: {file_path} ({len(self.data)} bytes)")

    def read_str(self, off):
        if not self.data or off < 0 or off >= len(self.data): 
            return ""
        chars = []
        while off < len(self.data) and self.data[off] != 0:
            chars.append(self.data[off])
            off += 1
            if len(chars) > 256:
                break
        return bytes(chars).decode('utf-8', errors='ignore')

    def parse_entities(self):
        if not self.data:
            debug_print("No MPB data loaded")
            return {'entities': [], 'groups': []}

        try:
            group_list_off = struct.unpack('<I', self.data[4:8])[0]
            group_list_count = struct.unpack('<I', self.data[8:12])[0]
        except Exception as e:
            debug_print(f"Failed to parse MPB header: {e}")
            return {'entities': [], 'groups': []}

        debug_print(f"MPB has {group_list_count} groups at offset 0x{group_list_off:X}")

        entities = []
        groups = {}

        for i in range(group_list_count):
            item_off = group_list_off + (i * 0x30)
            if item_off + 0x30 > len(self.data): 
                break

            eg_offsets_rel, eg_count = struct.unpack('<II', self.data[item_off+0x28 : item_off+0x30])
            base_eg = item_off + eg_offsets_rel

            for j in range(eg_count):
                eg_ptr = base_eg + (j * 0x3C)
                if eg_ptr + 0x3C > len(self.data): 
                    break

                group_id = struct.unpack('<i', self.data[eg_ptr+4 : eg_ptr+8])[0]
                groups[group_id] = {'id': group_id}

                ent_offsets_rel, ent_count = struct.unpack('<II', self.data[eg_ptr+0x10 : eg_ptr+0x18])
                base_offsets = eg_ptr + ent_offsets_rel

                for k in range(ent_count):
                    off_ptr = base_offsets + (k * 4)
                    if off_ptr + 4 > len(self.data): 
                        break

                    me_rel_ptr = struct.unpack('<i', self.data[off_ptr:off_ptr+4])[0]
                    abs_entity_off = base_offsets + me_rel_ptr

                    if abs_entity_off < 0 or abs_entity_off + 128 > len(self.data): 
                        continue

                    e_type = struct.unpack('<I', self.data[abs_entity_off+4 : abs_entity_off+8])[0]
                    parent_group_id = struct.unpack('<i', self.data[abs_entity_off+0x0C : abs_entity_off+0x10])[0]

                    # Parse base transform
                    try:
                        px, py, pz = struct.unpack('<3d', self.data[abs_entity_off+0x10 : abs_entity_off+0x28])
                        rx, ry, rz = struct.unpack('<3f', self.data[abs_entity_off+0x28 : abs_entity_off+0x34])
                        gscl = struct.unpack('<f', self.data[abs_entity_off+0x34 : abs_entity_off+0x38])[0]
                    except:
                        continue

                    # Parse light data if type 2001
                    light_data = None
                    if e_type == 2001:
                        light_data = LightEntityParser.parse_light_data(self.data, abs_entity_off)

                    # Get file path for file-based entities
                    file_path = ""
                    if e_type in [1015, 1028, 1002, 5001]:
                        try:
                            file_base = abs_entity_off + 0x50
                            path_off_rel = struct.unpack('<i', self.data[file_base+4 : file_base+8])[0]
                            file_path = self.read_str(file_base + path_off_rel)
                        except:
                            pass

                    entity = {
                        'type': e_type,
                        'path': file_path,
                        'pos': (px, py, pz),
                        'rot': (rx, ry, rz),
                        'scl': (gscl, gscl, gscl),
                        'parent_group': parent_group_id,
                        'light_data': light_data,
                        'raw_offset': abs_entity_off
                    }
                    entities.append(entity)

        debug_print(f"Parsed {len(entities)} entities across {len(groups)} groups")
        return {'entities': entities, 'groups': list(groups.values())}


def parse_soa_coords(data, data_offset, count):
    if data_offset + (count * 12) > len(data):
        return []

    coords = []
    try:
        for i in range(count):
            base = data_offset + (i * 12)
            if base + 12 > len(data):
                break
            ix, iy, iz, irx, iry, irz = struct.unpack('<hhhhhh', data[base:base+12])
            coords.append((ix, iy, iz, irx, iry, irz))
    except Exception as e:
        debug_print(f"Coordinate parsing failed: {e}")
        return []

    return coords


def import_single_mdl(rel_path, parent_obj, global_cache, locator, mat_resolver):
    if global_cache is None: 
        global_cache = {}

    if rel_path.endswith(".ter"):
        rel_path = rel_path.replace(".ter", ".mdl")

    model_name = Path(rel_path).stem
    if "_LOD0" in model_name:
        model_name = model_name.replace("_LOD0", "")
    elif "_lod0" in model_name:
        model_name = model_name.replace("_lod0", "")

    if model_name in global_cache:
        base_obj = global_cache[model_name]
        new_obj = base_obj.copy()
        new_obj.data = base_obj.data.copy()
        bpy.context.collection.objects.link(new_obj)
        new_obj.parent = parent_obj
        new_obj.location = (0, 0, 0)
        return [new_obj]

    gltf_path = locator.find_mdl_gltf(rel_path) if locator else None
    if not gltf_path:
        placeholder = bpy.data.objects.new(f"MISSING_{model_name}", None)
        placeholder.empty_display_type = 'SPHERE'
        placeholder.empty_display_size = 0.2
        placeholder.parent = parent_obj
        bpy.context.collection.objects.link(placeholder)
        return [placeholder]

    try:
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.import_scene.gltf(filepath=str(gltf_path))
        imported = list(bpy.context.selected_objects)

        if not imported:
            return []

        first_mesh = None
        for obj in imported:
            if obj.type == 'MESH':
                if obj.data.materials:
                    for i, mat in enumerate(obj.data.materials):
                        if mat:
                            old_name = mat.name
                            new_name = model_name
                            mat.name = new_name
                            debug_print(f"  [Material] Renamed '{old_name}' -> '{new_name}'")

                if mat_resolver:
                    mat_resolver.relink_materials(obj, model_name)

                if first_mesh is None:
                    first_mesh = obj
                    global_cache[model_name] = obj

        for obj in imported:
            if obj.parent is None:
                obj.parent = parent_obj
                obj.location = (0, 0, 0)
                obj.rotation_euler = (0, 0, 0)
                obj.scale = (1, 1, 1)
            if obj.type == 'ARMATURE':
                obj.hide_viewport = True
                obj.hide_render = True

        return imported

    except Exception as e:
        debug_print(f"GLTF import failed for {rel_path}: {e}")
        return []


def import_light_entity(entity, parent_obj):
    """Import a light entity (Type 2001) into Blender."""
    light_data = entity.get('light_data')
    if not light_data:
        # Create a default point light if parsing failed
        light_type = 'POINT'
        color = (1.0, 1.0, 1.0)
        intensity = 100.0
        range_val = 10.0
    else:
        light_type = light_data['light_type']
        color = light_data['color']
        intensity = light_data['intensity']
        range_val = light_data['range']

    # Create light data
    l_name = f"LGT_{entity['raw_offset']:X}"

    try:
        if light_type == 'SUN':
            l_data = bpy.data.lights.new(name=l_name, type='SUN')
            l_data.energy = intensity / 100  # Sun lights use different scale
            l_data.color = color
        elif light_type == 'SPOT':
            l_data = bpy.data.lights.new(name=l_name, type='SPOT')
            l_data.energy = intensity
            l_data.color = color
            l_data.spot_size = math.radians(45)
            l_data.spot_blend = 0.15
        elif light_type == 'AREA':
            l_data = bpy.data.lights.new(name=l_name, type='AREA')
            l_data.energy = intensity
            l_data.color = color
            l_data.size = 1.0
        else:  # POINT
            l_data = bpy.data.lights.new(name=l_name, type='POINT')
            l_data.energy = intensity
            l_data.color = color

        # Set custom property for range (Blender doesn't have direct range for point lights)
        l_data["ff16_range"] = range_val

        # Create light object
        l_obj = bpy.data.objects.new(name=l_name, object_data=l_data)
        bpy.context.collection.objects.link(l_obj)
        l_obj.parent = parent_obj

        # Apply transform from parent (entity empty)
        l_obj.location = (0, 0, 0)
        l_obj.rotation_euler = (0, 0, 0)

        if light_data:
            debug_print(f"  [Light] Imported {light_type} light: RGB({color[0]:.2f}, {color[1]:.2f}, {color[2]:.2f}), Intensity={intensity:.1f}")
            if light_data.get('shaking_param_id', 0) != 0:
                debug_print(f"  [Light] Has shaking params (ID: {light_data['shaking_param_id']})")
        else:
            debug_print(f"  [Light] Imported default point light (parsing failed)")

        return l_obj

    except Exception as e:
        debug_print(f"  [Light] Failed to create light: {e}")
        return None


def import_ssb(path_to_ssb, parent_obj, global_cache, locator, mat_resolver):
    if not path_to_ssb.endswith('.ssb'):
        return

    full_ssb_path = Path(STAGESET_ROOT) / path_to_ssb.replace('/', os.sep)

    if not full_ssb_path.exists():
        debug_print(f"SSB not found: {full_ssb_path}")
        return

    try:
        with open(full_ssb_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        debug_print(f"Failed to read SSB: {e}")
        return

    try:
        header = struct.unpack('<16I', data[:64])
        data_offset = header[0]
        count = header[1]
        index_offset = header[2]
        ptr_list_off = header[3]
        string_count = header[4]
    except Exception as e:
        debug_print(f"Invalid SSB header in {path_to_ssb}: {e}")
        return

    debug_print(f"SSB {full_ssb_path.name}: {count} instances, {string_count} models")

    strings = []
    try:
        for i in range(string_count):
            ptr_abs = ptr_list_off + (i * 4)
            rel_off = struct.unpack('<i', data[ptr_abs:ptr_abs+4])[0]
            str_abs = ptr_abs + rel_off
            if str_abs > len(data):
                continue
            s_end = data.find(b'\x00', str_abs)
            if s_end == -1:
                s_end = len(data)
            s = data[str_abs:s_end].decode('utf-8', errors='ignore')
            if s:
                strings.append(s)
    except Exception as e:
        debug_print(f"String table parsing failed: {e}")
        return

    if not strings:
        debug_print("No model strings found in SSB")
        return

    try:
        shorts = struct.unpack(f'<{count}H', data[index_offset:index_offset + (count*2)])
    except Exception as e:
        debug_print(f"Index array parsing failed: {e}")
        return

    coords = parse_soa_coords(data, data_offset, count)
    if not coords:
        debug_print(f"WARNING: No coordinates parsed from {path_to_ssb}")
        return

    success = 0
    for i in range(min(count, len(coords))):
        try:
            str_idx = shorts[i] // 4
            if str_idx >= len(strings):
                continue

            mdl_path = strings[str_idx]
            if not mdl_path.endswith('.mdl'):
                continue

            imported = import_single_mdl(mdl_path, parent_obj, global_cache, locator, mat_resolver)
            if not imported:
                continue

            ix, iy, iz, irx, iry, irz = coords[i]

            lx = ix * GLOBAL_SCALE
            ly = iy * GLOBAL_SCALE
            lz = iz * GLOBAL_SCALE

            world_pos = (lx, -lz, ly)

            rx = math.radians(irx * 0.01)
            ry = math.radians(iry * 0.01)
            rz = math.radians(irz * 0.01)
            world_rot = (rx, -rz, ry)

            for obj in imported:
                if obj.parent == parent_obj:
                    obj.location = world_pos
                    obj.rotation_mode = 'XYZ'
                    obj.rotation_euler = world_rot

            success += 1

        except Exception as e:
            debug_print(f"Error on instance {i}: {e}")
            continue

    debug_print(f"  Imported {success}/{count} instances")


def import_nmb(nmb_rel_path, parent_obj, global_cache):
    if nmb_rel_path.startswith('/') or nmb_rel_path.startswith('\\'):
        nmb_rel_path = nmb_rel_path[1:]

    full_path = Path(STAGESET_ROOT) / nmb_rel_path

    if not full_path.exists():
        debug_print(f"  [NMB] File not found: {full_path}")
        return

    if full_path in global_cache:
        obj = global_cache[full_path].copy()
        obj.parent = parent_obj
        obj.matrix_local = mathutils.Matrix()
        bpy.context.collection.objects.link(obj)
        debug_print(f"  [NMB] Instanced {full_path.name}")
        return

    vertices = []
    try:
        with open(full_path, 'rb') as f:
            data = f.read()

        v_start = 0x6E50
        v_stride = 16

        if v_start >= len(data):
            debug_print(f"  [NMB] File too small for hardcoded offset {hex(v_start)}")
            return

        for i in range(5000):
            off = v_start + (i * v_stride)
            if off + 12 > len(data):
                break

            x, y = struct.unpack('<ff', data[off:off+8])
            vertices.append((x, 0, y)) 

    except Exception as e:
        debug_print(f"  [NMB] Error parsing {full_path.name}: {e}")
        return

    if not vertices:
        return

    mesh = bpy.data.meshes.new(full_path.name)
    mesh.from_pydata(vertices, [], [])
    mesh.update()

    obj = bpy.data.objects.new(full_path.name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent_obj

    global_cache[full_path] = obj
    debug_print(f"  [NMB] Imported {len(vertices)} vertices from {full_path.name}")


def run_importer():
    debug_print("Starting import...")

    locator = AssetLocator(CONVERTED_ROOT)
    mat_resolver = FF16MaterialResolver(CONVERTED_ROOT, CONVERTED_ROOT)

    parser = MpbParser(MPB_PATH)
    result = parser.parse_entities()
    entities = result['entities']
    groups_info = result['groups']

    if not entities:
        debug_print("No entities found! Check MPB path.")
        return

    # Create group hierarchy
    group_map = {}
    for g in groups_info:
        gid = g['id']
        g_mt = bpy.data.objects.new(f"GRP_{gid}", None)
        bpy.context.collection.objects.link(g_mt)
        group_map[gid] = g_mt

    global_cache = {}

    # Process entities
    for idx, ent in enumerate(entities):
        path_name = Path(ent['path']).name if ent['path'] else f"entity_{ent['raw_offset']:X}"
        debug_print(f"[{idx+1}/{len(entities)}] {path_name} (Type {ent['type']})")

        # Create empty at MPB transform (world position)
        parent = bpy.data.objects.new(f"ENT_{path_name}", None)
        bpy.context.collection.objects.link(parent)

        if ent['parent_group'] in group_map:
            parent.parent = group_map[ent['parent_group']]

        # Apply MPB transform (Game Y-up to Blender Z-up)
        px, py, pz = ent['pos']
        parent.location = (px, -pz, py)
        parent.rotation_mode = 'XYZ'
        rx, ry, rz = ent['rot']
        parent.rotation_euler = (rx, -rz, ry)
        parent.scale = ent['scl']

        # Import based on type
        if ent['type'] == 1015 and ent['path'].endswith('.ssb'):
            import_ssb(ent['path'], parent, global_cache, locator, mat_resolver)
        elif ent['type'] == 1028 and ent['path'].endswith('.mdl'):
            import_single_mdl(ent['path'], parent, global_cache, locator, mat_resolver)
        elif ent['type'] == 2001:
            # Light entity - import with proper light data
            import_light_entity(ent, parent)
        elif ent['type'] == 5001:
            try:
                import_nmb(ent['path'], parent, global_cache)
            except Exception as e:
                debug_print(f"  Failed to import NMB {ent['path']}: {e}")

    debug_print("Import complete!")


if __name__ == "__main__":
    run_importer()
