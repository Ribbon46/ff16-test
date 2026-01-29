import struct
import os
from collections import defaultdict

MPB_PATH = r"G:\16 extract 2\map\t\a01\a00\t_a01_a00.mpb"

def read_str(data, off):
    chars = []
    while off < len(data) and data[off] != 0:
        chars.append(data[off])
        off += 1
    return bytes(chars).decode('utf-8', errors='ignore')

def main():
    with open(MPB_PATH, 'rb') as f:
        data = f.read()

    group_list_off = struct.unpack('<I', data[4:8])[0]
    group_list_count = struct.unpack('<I', data[8:12])[0]
    
    entities = []
    for i in range(group_list_count):
        item_off = group_list_off + (i * 0x30)
        eg_offsets_rel, eg_count = struct.unpack('<II', data[item_off+0x28:item_off+0x30])
        base_eg = item_off + eg_offsets_rel
        for j in range(eg_count):
            eg_ptr = base_eg + (j * 0x3C)
            ent_offsets_rel, ent_count = struct.unpack('<II', data[eg_ptr+0x10:eg_ptr+0x18])
            base_offsets = eg_ptr + ent_offsets_rel
            for k in range(ent_count):
                off_ptr = base_offsets + (k * 4)
                me_rel_ptr = struct.unpack('<i', data[off_ptr:off_ptr+4])[0]
                abs_entity_off = base_offsets + me_rel_ptr
                e_type = struct.unpack('<I', data[abs_entity_off+4:abs_entity_off+8])[0]
                px, py, pz = struct.unpack('<3d', data[abs_entity_off+0x10:abs_entity_off+0x28])
                path = ""
                if e_type in [1015, 1028, 1002, 5001]:
                    file_base = abs_entity_off + 0x50
                    path_off_rel = struct.unpack('<i', data[file_base+4:file_base+8])[0]
                    path = read_str(data, file_base + path_off_rel)
                
                # Full 32-byte header snapshot for flag analysis
                header = data[abs_entity_off:abs_entity_off+32].hex()
                entities.append({'type': e_type, 'path': path, 'pos': (px, py, pz), 'hex': header})

    # Find co-located entities (within 0.01)
    seen_pos = defaultdict(list)
    for ent in entities:
        if not ent['path']: continue
        # Round pos to reduce jitter
        rpos = (round(ent['pos'][0], 2), round(ent['pos'][1], 2), round(ent['pos'][2], 2))
        seen_pos[rpos].append(ent)

    print("--- OVERLAPPING ENTITIES ---")
    for pos, list_ents in seen_pos.items():
        if len(list_ents) > 1:
            # Only print if different paths
            paths = set(e['path'] for e in list_ents)
            if len(paths) > 1:
                print(f"Pos: {pos}")
                for e in list_ents:
                    print(f"  Type {e['type']} | {e['path']} | Hex: {e['hex']}")
                print("-" * 40)

if __name__ == '__main__':
    main()
