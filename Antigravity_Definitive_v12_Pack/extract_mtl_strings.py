import re
import os

MTL_PATH = r"G:\16 extract\env\bgparts\t\a01\material\m_bt_a01_reli_crackwall01a.mtl"

def main():
    if not os.path.exists(MTL_PATH):
        print("MTL not found")
        return
    with open(MTL_PATH, 'rb') as f:
        data = f.read()
    
    # Find patterns looking like paths: starting with / and contains only alphanumeric/_/
    paths = re.findall(b'/[a-zA-Z0-9_/]+', data)
    for p in paths:
        print(p.decode(errors='ignore'))

if __name__ == '__main__':
    main()
