import xml.etree.ElementTree as ET
import os

# ==========================================
# CONFIGURATION
# ==========================================
INPUT_XML = "ready_for_import_16.xml"   
OUTPUT_XML = "ready_for_import_16_shifted.xml"  

# Set your offset here! 
# Example: -1 shifts everything BACKWARD one frame. Frame 0 gets permanently deleted.
FRAME_OFFSET = -1  

# ==========================================
# RUN SHIFT
# ==========================================
def shift_cvat_timeline():
    print(f"Loading {INPUT_XML}...")
    tree = ET.parse(INPUT_XML)
    root = tree.getroot()
    deleted_count = 0

    # 1. Shift elements nested inside <track> tags (like <skeleton>, <box>)
    for track in root.findall('.//track'):
        # We wrap it in list() so we can safely delete elements while looping over them
        for elem in list(track): 
            if 'frame' in elem.attrib:
                new_frame = int(elem.attrib['frame']) + FRAME_OFFSET
                
                if new_frame < 0:
                    track.remove(elem)
                    deleted_count += 1
                else:
                    elem.attrib['frame'] = str(new_frame)
            
    # 2. Shift standalone <image> tags (if using CVAT for Images format)
    for image in list(root):
        if image.tag == 'image' and 'id' in image.attrib:
            new_id = int(image.attrib['id']) + FRAME_OFFSET
            
            if new_id < 0:
                root.remove(image)
                deleted_count += 1
            else:
                image.attrib['id'] = str(new_id)

    # Save the file
    tree.write(OUTPUT_XML, encoding='utf-8', xml_declaration=True)
    print(f"✅ Success! Shifted all annotations by {FRAME_OFFSET} frames.")
    if deleted_count > 0:
        print(f"🗑️ Cleaned up: Safely deleted {deleted_count} frames that dropped below 0.")
    print(f"Saved as: {OUTPUT_XML}")

if os.path.exists(INPUT_XML):
    shift_cvat_timeline()
else:
    print("❌ Error: Could not find the input XML file.")