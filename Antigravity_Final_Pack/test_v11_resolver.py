from ffxvi_utils import UniversalMaterialResolver

def main():
    print("Testing UniversalMaterialResolver v11 Patch...")
    # Use my known roots
    MTL_GLOBAL_ROOTS = [r"G:\16 extract", r"G:\16 extract 2"]
    TEXTURE_ROOTS = [r"G:\16 extract\converted files"]
    
    resolver = UniversalMaterialResolver(MTL_GLOBAL_ROOTS, TEXTURE_ROOTS)
    
    test_cases = [
        "bt_a01_reli_crackwall01a",
        "bt_01a_buil_plazastep01_01", # Actual material in woodstep03
        "bt_a01_buil_churchdoor01",
        "bt_a01_grou_stone03a",
    ]
    
    for mat in test_cases:
        res = resolver.resolve(mat)
        if res:
            print(f"Material: {mat} -> {res['base'].name} (Via {res['source']})")
        else:
            print(f"Material: {mat} -> FAILED")

if __name__ == "__main__":
    main()
