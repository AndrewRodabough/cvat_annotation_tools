import xml.etree.ElementTree as ET
import os

def remap_cvat_xml(input_xml, output_xml, parent_map, joint_map):
    tree = ET.parse(input_xml)
    root = tree.getroot()

    # Iterate through all <track> elements (the parent skeletons)
    for track in root.findall('.//track'):
        old_track_label = track.get('label')
        
        # 1. Swap the Parent Label
        if old_track_label in parent_map:
            track.set('label', parent_map[old_track_label])
            
        # 2. Swap or Delete the Joint Labels
        # We must iterate through the <skeleton> nodes first so we can delete children from them
        for skeleton in track.findall('.//skeleton'):
            # Find all <points> inside this specific skeleton frame
            for points in skeleton.findall('./points'):
                old_joint_label = points.get('label')
                
                if old_joint_label in joint_map:
                    # It exists in our map! Rename it.
                    points.set('label', str(joint_map[old_joint_label]))
                else:
                    # It is NOT in our map. Delete it completely.
                    skeleton.remove(points)

    # Save the modified XML
    tree.write(output_xml, encoding='utf-8', xml_declaration=True)
    print(f"✅ Successfully remapped, cleaned, and saved to {output_xml}")


# ==========================================
# CONFIGURATION
# ==========================================

PARENT_MAP = {
    "Person": "skeleton"
}

# Map old joint numbers to new joint numbers/names
# Format: "Old_Name": "New_Name"
JOINT_MAP = {
    "1": "3",
    "3": "1",
    "5": "2",
    "16": "5",
    "6": "11",
    "7": "10",
    "8": "9",
    "11": "8",
    "12": "7",
    "13": "6",
    "20": "13",
    "24": "12",
    "41": "14",
    "21": "18",
    "25": "19",
    "26": "20",
    "23": "15",
    "27": "16",
    "28": "17",
    "29": "27",
    "30": "28",
    "33": "25",
    "34": "26",
    "35": "23",
    "36": "24",
    "39": "21",
    "40": "22"
}

# ==========================================
# RUN THE SCRIPT
# ==========================================
input_filename = "job_16_cvat_import.xml"
output_filename = "ready_for_import_16.xml"

if os.path.exists(input_filename):
    remap_cvat_xml(input_filename, output_filename, PARENT_MAP, JOINT_MAP)
else:
    print(f"❌ Could not find {input_filename}")