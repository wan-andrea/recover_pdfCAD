"""
Group Visualizer: Creates a visual PDF from detected groups. STEP 3

This script reads the groups.json output from find_groups.py and generates
a new PDF that shows the original drawing overlaid with colored bounding boxes
around each detected group (cluster of related shapes).

Usage:
    python visualize_groups.py --input example1.pdf --data output_data.json --groups detected_groups.json --output final_visual.pdf
"""

import json
import argparse
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, DecodedStreamObject, ArrayObject
import colorsys
import random

def load_json(json_file):
    with open(json_file, 'r') as f:
        return json.load(f)

def generate_group_colors(n):
    colors = []
    for i in range(n):
        hue = i / n
        sat = 0.9; val = 0.8
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        colors.append((r, g, b))
    random.shuffle(colors)
    return colors

def transform_point(x, y, matrix):
    a, b, c, d, e, f = matrix
    nx = a*x + c*y + e
    ny = b*x + d*y + f
    return nx, ny

def calculate_group_bbox(group_members, instances_map):
    if not group_members: return None
    global_xs, global_ys = [], []
    
    for instance_id in group_members:
        if instance_id not in instances_map: continue
        inst = instances_map[instance_id]
        bbox_local = inst['bbox_local'] # [minx, miny, maxx, maxy]
        m = inst['transform_matrix']
        
        local_corners = [
            (bbox_local[0], bbox_local[1]),
            (bbox_local[2], bbox_local[1]),
            (bbox_local[2], bbox_local[3]),
            (bbox_local[0], bbox_local[3])
        ]
        
        for lx, ly in local_corners:
            gx, gy = transform_point(lx, ly, m)
            global_xs.append(gx)
            global_ys.append(gy)
            
    if not global_xs: return None
    return (min(global_xs), min(global_ys), max(global_xs), max(global_ys))

def create_visualization_pdf(input_pdf, data_json, groups_json, output_pdf):
    print("Loading JSON data...")
    raw_data = load_json(data_json)
    groups_data = load_json(groups_json)
    
    instances_map = {inst['instance_id']: inst for inst in raw_data['instances']}
    
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    
    n_groups = len(groups_data['group_instances'])
    group_colors = generate_group_colors(n_groups)
    
    print(f"Visualizing {n_groups} groups...")
    
    for page_num, page in enumerate(reader.pages):
        current_page_idx = page_num + 1
        groups_on_page = [g for g in groups_data['group_instances'] if g['page'] == current_page_idx]
        
        if not groups_on_page:
            writer.add_page(page)
            continue
            
        print(f"  Page {current_page_idx}: Drawing {len(groups_on_page)} boxes...")
        
        draw_cmds = []
        for i, group in enumerate(groups_on_page):
            bbox = calculate_group_bbox(group['members'], instances_map)
            if bbox:
                min_x, min_y, max_x, max_y = bbox
                w = max_x - min_x
                h = max_y - min_y
                if w < 1 or h < 1: continue 
                
                color = group_colors[i % len(group_colors)]
                r, g, b = color
                
                # Simple Stroke Command (No transparency/GS)
                # q = save, RG = stroke color, w = width, re = rect, S = stroke, Q = restore
                cmd = (
                    f"q {r:.2f} {g:.2f} {b:.2f} RG 5 w "
                    f"{min_x:.2f} {min_y:.2f} {w:.2f} {h:.2f} re S Q"
                )
                draw_cmds.append(cmd)

        if draw_cmds:
            final_stream_data = "\n".join(draw_cmds)
            new_stream = DecodedStreamObject()
            new_stream.set_data(final_stream_data.encode('latin-1'))
            
            # CRITICAL FIX: Register object with writer BEFORE adding to page content array
            # We can't do this easily with PyPDF2 in this order because the page belongs to 'reader' 
            # and we are adding it to 'writer' later.
            
            # Solution: We modify the page object BEFORE adding it to the writer.
            # But the new stream needs to be an IndirectObject.
            
            # We can cheat by using writer.add_object() but we don't have the writer reference easily inside the loop 
            # unless we add the page first? No.
            
            # Actually, PyPDF2's ArrayObject.append() expects a reference if we are cloning.
            # The easiest fix is to just let the writer handle the stream creation via `writer.add_page`.
            # But we are modifying the page in place.
            
            # Robust Fix:
            # 1. Create the stream.
            # 2. Add the page to the writer (it clones the reader's page).
            # 3. Modify the CLONED page in the writer.
            
            # Let's change the loop structure:
            
            pass # We will handle logic below to avoid nesting depth
            
        # Add original page to writer FIRST
        page_ref = writer.add_page(page)
        
        # Now get the page object BACK from the writer (it is now part of the writer's tree)
        # page_ref is usually the IndirectObject, we need the actual PageObject
        writer_page = page_ref.get_object() 
        
        if draw_cmds:
            # Create the stream and register it with the writer
            final_stream_data = "\n".join(draw_cmds)
            new_stream = DecodedStreamObject()
            new_stream.set_data(final_stream_data.encode('latin-1'))
            
            # Add stream to writer's objects to get a reference
            stream_ref = writer._add_object(new_stream)
            
            # Now append that reference to the page's contents
            if "/Contents" in writer_page:
                contents = writer_page["/Contents"]
                if isinstance(contents, ArrayObject):
                    contents.append(stream_ref)
                else:
                    new_contents = ArrayObject([contents, stream_ref])
                    writer_page[NameObject("/Contents")] = new_contents
            else:
                writer_page[NameObject("/Contents")] = stream_ref

    with open(output_pdf, 'wb') as f:
        writer.write(f)
    print(f"Success: {output_pdf}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--groups', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    create_visualization_pdf(args.input, args.data, args.groups, args.output)

if __name__ == "__main__":
    main()