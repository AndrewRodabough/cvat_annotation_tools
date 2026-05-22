import xml.etree.ElementTree as ET
import os

# ==========================================
# CONFIGURATION
# ==========================================
BASE_XML = "annotations_42.xml"             # Your clean bounding box file
OLD_XML = "ready_for_import_42.xml"      # Your remapped old skeletons
OUTPUT_XML = "final_merged_upload_42.xml"   # The file you will upload

def merge_files():
    print(f"Loading Base XML: {BASE_XML}")
    tree_base = ET.parse(BASE_XML)
    root_base = tree_base.getroot()

    print(f"Loading Old XML: {OLD_XML}")
    tree_old = ET.parse(OLD_XML)
    root_old = tree_old.getroot()

    # 1. Find the highest ID in your bounding box file to prevent collisions
    max_id = 0
    for elem in root_base.iter():
        if 'id' in elem.attrib:
            try:
                max_id = max(max_id, int(elem.attrib['id']))
            except ValueError:
                pass
                
    id_offset = max_id + 1000
    print(f"Base Max ID is {max_id}. Offsetting old tracks by {id_offset}...")
    
    # 2. Extract only the tracks from the old file and re-index them
    count = 0
    for track in root_old.findall('track'):
        if 'id' in track.attrib:
            track.attrib['id'] = str(int(track.attrib['id']) + id_offset)
            
        # Safely append the track to the base file
        root_base.append(track)
        count += 1
        
    # 3. Save the hybrid file
    tree_base.write(OUTPUT_XML, encoding='utf-8', xml_declaration=True)
    print(f"✅ Success! Injected {count} skeleton tracks into your bounding box file.")
    print(f"Saved as: {OUTPUT_XML}")

if os.path.exists(BASE_XML) and os.path.exists(OLD_XML):
    merge_files()
else:
    print("❌ Error: Missing input files. Please check the filenames!")