import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom

print("Loading original CSV files...")
labels_df = pd.read_csv('old_labels.csv')
tracks_df = pd.read_csv('old_tracks.csv')
shapes_df = pd.read_csv('old_tracked_shapes.csv')

# Build Label Map
joint_labels = labels_df[labels_df['parent_id'].notna()]
label_id_to_name = dict(zip(joint_labels['id'], joint_labels['name']))

# Filter shapes to only include valid joints
valid_shapes = shapes_df.dropna(subset=['points']).copy()
valid_shapes['outside_bin'] = valid_shapes['outside'].apply(lambda x: '1' if x == 't' else '0')
valid_shapes['occluded_bin'] = valid_shapes['occluded'].apply(lambda x: '1' if x == 't' else '0')

# Process each video clip / job individually
for job_id in tracks_df['job_id'].unique():
    job_tracks = tracks_df[tracks_df['job_id'] == job_id].sort_values('id')
    
    # Isolate parent skeletons vs child joints
    persons = job_tracks[job_tracks['label_id'] == 143]['id'].tolist()
    joints = job_tracks[job_tracks['label_id'] != 143]['id'].tolist()
    
    joint_track_to_person = {}
    joint_track_to_label_name = {}
    
    # CVAT stores exactly 46 joints sequentially right after the parent track
    for i, p_id in enumerate(persons):
        p_joints = joints[i*46 : (i+1)*46]
        for j_id in p_joints:
            joint_track_to_person[j_id] = p_id
            
            l_id = job_tracks[job_tracks['id'] == j_id]['label_id'].values[0]
            joint_track_to_label_name[j_id] = str(label_id_to_name[l_id])
    
    # Pull shapes specifically for this job's tracks
    job_shape_tracks = valid_shapes[valid_shapes['track_id'].isin(joint_track_to_person.keys())]
    
    person_frames = {p: {} for p in persons}
    
    # Group coordinates by Person -> Frame
    for _, row in job_shape_tracks.iterrows():
        t_id = row['track_id']
        p_id = joint_track_to_person[t_id]
        frame = str(row['frame'])
        
        if frame not in person_frames[p_id]:
            person_frames[p_id][frame] = []
            
        person_frames[p_id][frame].append({
            'label': joint_track_to_label_name[t_id],
            'points': row['points'],
            'outside': row['outside_bin'],
            'occluded': row['occluded_bin']
        })
    
    # Construct the CVAT 1.1 XML Tree
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    
    for p_id in persons:
        if not person_frames[p_id]:
            continue
            
        track_elem = ET.SubElement(root, "track", id=str(p_id), label="Person")
        frames = sorted(person_frames[p_id].keys(), key=int)
        
        for f in frames:
            skel_elem = ET.SubElement(track_elem, "skeleton", frame=f, outside="0", occluded="0", keyframe="1")
            for jnt in person_frames[p_id][f]:
                ET.SubElement(skel_elem, "points", 
                              label=jnt['label'], 
                              points=jnt['points'], 
                              outside=jnt['outside'], 
                              occluded=jnt['occluded'], 
                              keyframe="1")
                              
    # Format and save
    xmlstr = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
    filename = f'job_{job_id}_cvat_import.xml'
    with open(filename, 'w') as f:
        f.write(xmlstr)
    print(f"✅ Successfully created {filename}")