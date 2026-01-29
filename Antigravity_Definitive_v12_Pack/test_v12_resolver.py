from ffxvi_utils import UniversalMaterialResolver
from pathlib import Path

# --- CONFIG ---
MTL_ROOTS = [r"G:\16 extract", r"G:\16 extract 2"]
TEXTURE_ROOTS = [r"G:\16 extract\converted files"]

def run_test():
    resolver = UniversalMaterialResolver(MTL_ROOTS, TEXTURE_ROOTS)
    
    test_cases = [
        # The complex modular one (Needs MTL)
        "bt_a01_reli_crackwall01a",
        # The keyword one (Needs specific ID extraction)
        "bt_01a_buil_plazastep01_01",
        # The woodstep one
        "bt_a01_buil_woodstep03",
        # A generic one that should NOT match mothercrystal
        "bt_a01_reli_generic"
    ]
    
    print("\n" + "="*50)
    print("FF16 v12 MATERIAL RESOLUTION TEST")
    print("="*50)
    
    # DEBUG: See what "step" textures we actually have
    step_tex = [k for k in resolver.texture_cache.keys() if "step" in k]
    print(f"DEBUG: Found {len(step_tex)} textures with 'step' in name.")
    if step_tex:
        print(f"DEBUG: Sample step textures: {step_tex[:10]}")

    with open(r"G:\16 extract\v12_test_results_utf8.txt", "w", encoding="utf-8") as f:
        f.write("FF16 v12 MATERIAL RESOLUTION TEST\n")
        f.write(f"DEBUG: Found {len(step_tex)} textures with 'step' in name.\n")
        if step_tex:
            f.write(f"DEBUG: Step textures: {', '.join(step_tex)}\n")
        f.write("="*50 + "\n")
        for mat in test_cases:
            f.write(f"\nResolving: {mat}\n")
            res = resolver.resolve(mat)
            if res:
                f.write(f"  TARGET: {res['base'].name}\n")
                f.write(f"  SOURCE: {res['source']}\n")
            else:
                f.write("  FAILED: No match found.\n")
        f.write("="*50 + "\n")
    
    print("Results written to G:\\16 extract\\v12_test_results_utf8.txt")

if __name__ == "__main__":
    run_test()
