import pandas as pd
import json

# 1. Load the raw data
print("Loading CSV files...")
labels_df = pd.read_csv('old_labels.csv')
tracks_df = pd.read_csv('old_tracks.csv')
shapes_df = pd.read_csv('old_tracked_shapes.csv')

# 2. Build our Label Mapping
# Find the IDs for the joints (sub-labels of the 'Person' class)
joint_labels = labels_df[labels_df['parent_id'].notna()]
label_id_to_name = dict(zip(joint_labels['id'], joint_labels['name']))

# 3. Merge Tracks with Shapes
# This gives every X,Y coordinate row its proper label_id (so we know which joint it is)
merged_df = pd.merge(shapes_df, tracks_df, left_on='track_id', right_on='id', suffixes=('_shape', '_track'))

# 4. Reconstruct the Skeletons
print("Stitching joints back into skeletons...")
# To figure out which joint belongs to which person, we group by job and frame
# Then we can group tracks into blocks of 46 (since each person has 46 joints)
frames_data = {}

for _, row in merged_df.iterrows():
    job = row['job_id']
    frame = row['frame']
    label_id = row['label_id']
    track_id = row['track_id']
    
    # Skip parent bounding boxes/empty points, we only want the actual joints
    if label_id not in label_id_to_name or pd.isna(row['points']):
        continue
        
    joint_name = label_id_to_name[label_id]
    
    # Extract the X, Y coordinates
    coords = [float(c) for c in str(row['points']).split(',')]
    
    # Create nested dictionary structure: frames_data[job][frame][person_instance]
    if job not in frames_data:
        frames_data[job] = {}
    if frame not in frames_data[job]:
        frames_data[job][frame] = {}
        
    # We use integer division on the track_id to group the 46 tracks into "Person 1", "Person 2", etc.
    # Because CVAT creates the 46 joint tracks sequentially in the database!
    person_instance_id = track_id // 50  
    
    if person_instance_id not in frames_data[job][frame]:
        frames_data[job][frame][person_instance_id] = {}
        
    # Store the joint
    frames_data[job][frame][person_instance_id][joint_name] = {
        "x": coords[0],
        "y": coords[1],
        "occluded": row['occluded'] == 't',
        "outside": row['outside'] == 't'
    }

# 5. Format for the New System (JSON)
output_annotations = []

for job, frames in frames_data.items():
    for frame_num, persons in frames.items():
        for person_id, joints in persons.items():
            
            # Format this however your new 2026 system requires!
            # Here is a standard generic Keypoint representation:
            skeleton_instance = {
                "job_id": int(job),
                "frame": int(frame_num),
                "label": "Person",
                "joints": joints
            }
            output_annotations.append(skeleton_instance)

# 6. Save to disk
with open('remapped_skeletons.json', 'w') as f:
    json.dump(output_annotations, f, indent=4)

print(f"Success! Reconstructed {len(output_annotations)} skeleton frames.")