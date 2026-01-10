"""
PDF Shape Cropper STEP 2 (v5 - Global Transform Awareness)
==========================================================

Fixes the "Blank/Wrong Image" issue by parsing the Global Page Transformation Matrix.
1. Reads the raw PDF content stream header.
2. Extracts the initial 'cm' operator (the Global Scale Factor) that Step 1 ignored.
3. Applies this transform to the JSON coordinates.
4. Crops accurately in PyMuPDF's coordinate space.

Usage:
    python crop_shapes.py --pdf example1.pdf --json step1_with_markers.json --output crops/
"""

import fitz  # PyMuPDF
import json
import argparse
import os
import re

# ------------------------------------------------------------------------------
# MATH UTILS
# ------------------------------------------------------------------------------

def mult_matrix(m1, m2):
    """Multiplies two 3x3 matrices (represented as 6-float lists)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [
        a1*a2 + b1*c2,       a1*b2 + b1*d2,
        c1*a2 + d1*c2,       c1*b2 + d1*d2,
        e1*a2 + f1*c2 + e2,  e1*b2 + f1*d2 + f2
    ]

def transform_point(x, y, matrix):
    a, b, c, d, e, f = matrix
    return (a*x + c*y + e, b*x + d*y + f)

def get_raw_aabb(instance):
    """Calculates AABB in Step 1's Local Coordinate Space."""
    bbox = instance['bbox_local']
    matrix = instance['transform_matrix']
    corners = [
        (bbox[0], bbox[1]), (bbox[2], bbox[1]),
        (bbox[2], bbox[3]), (bbox[0], bbox[3]),
    ]
    transformed = [transform_point(x, y, matrix) for x, y in corners]
    xs = [p[0] for p in transformed]
    ys = [p[1] for p in transformed]
    return (min(xs), min(ys), max(xs), max(ys))

# ------------------------------------------------------------------------------
# GLOBAL TRANSFORM EXTRACTION
# ------------------------------------------------------------------------------

def get_global_transform(page):
    """
    Parses the page content stream to find the Global CTM (Current Transformation Matrix).
    This is usually a 'cm' operator at the very start of the stream, before any 'q' or 'BT'.
    Step 1 ignored this, so we must apply it to align coordinates.
    """
    try:
        raw_bytes = page.read_contents()
        text = raw_bytes.decode('latin-1', errors='ignore')
    except:
        return [1,0,0,1,0,0]

    # Remove comments
    text = re.sub(r'%.*', '', text)
    
    # Find the boundary where "Global Scope" ends.
    # Usually the first 'q' (Save Graphics) or 'BT' (Begin Text) or 'Do' (Draw Object).
    limit_match = re.search(r'\b(q|BT|Do)\b', text)
    limit_index = limit_match.start() if limit_match else 1000 # Check first 1k chars if no marker
    
    header = text[:limit_index]
    
    # Find all 'cm' operators in this header
    cm_matches = re.findall(r'([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+cm', header)
    
    # Identity Matrix
    global_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    
    if not cm_matches:
        return global_matrix

    print(f"  Found {len(cm_matches)} global transform(s) in page header.")
    
    for match in cm_matches:
        args = [float(x) for x in match]
        # PDF Spec: New_CTM = Matrix x Old_CTM
        # We start with Identity, so we just accumulate them.
        # Order of multiplication: args x global_matrix
        
        # Note: 'mult_matrix' defined above implements m1 x m2
        global_matrix = mult_matrix(args, global_matrix)
        
    print(f"  -> Global Matrix: {global_matrix}")
    return global_matrix

# ------------------------------------------------------------------------------
# CROPPING PIPELINE
# ------------------------------------------------------------------------------

def crop_shapes(pdf_path, json_path, output_dir, padding=10, dpi=150):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"Loading JSON from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)
        
    print(f"Loading PDF from {pdf_path}...")
    doc = fitz.open(pdf_path)
    
    # Cache global transforms per page to avoid re-parsing
    page_transforms = {}
    
    # Render Matrix
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    
    count = 0
    skipped = 0
    
    print(f"Processing instances...")
    
    for i, instance in enumerate(data['instances']):
        page_num = instance['page']
        shape_id = instance['shape_id']
        instance_id = instance.get('instance_id', i)
        
        if page_num > len(doc): continue
        page = doc[page_num - 1]
        
        # 1. Fetch/Compute Global Matrix for this page
        if page_num not in page_transforms:
            page_transforms[page_num] = get_global_transform(page)
        
        global_matrix = page_transforms[page_num]
        
        # 2. Get Raw Coords (Local CAD Space)
        raw_min_x, raw_min_y, raw_max_x, raw_max_y = get_raw_aabb(instance)
        
        # 3. Apply Global Matrix to convert to PDF User Space
        # We transform the min/max points (approximation, but safe for axis-aligned scaling)
        # For strict correctness we should transform the 4 corners of the AABB
        corners = [
            (raw_min_x, raw_min_y), (raw_max_x, raw_min_y),
            (raw_max_x, raw_max_y), (raw_min_x, raw_max_y)
        ]
        
        final_pts = [transform_point(x, y, global_matrix) for x, y in corners]
        pdf_xs = [p[0] for p in final_pts]
        pdf_ys = [p[1] for p in final_pts]
        
        pdf_min_x, pdf_max_x = min(pdf_xs), max(pdf_xs)
        pdf_min_y, pdf_max_y = min(pdf_ys), max(pdf_ys)
        
        # 4. Handle Page Geometry (CropBox & Y-Flip)
        # Normalize Rotation
        original_rot = page.rotation
        if original_rot != 0: page.set_rotation(0)
        
        cropbox = page.cropbox
        
        # Map User Space -> PyMuPDF Image Space
        # X: Relative to CropBox Left
        rel_x1 = pdf_min_x - cropbox.x0
        rel_x2 = pdf_max_x - cropbox.x0
        
        # Y: Relative to CropBox TOP (Y-Flip)
        rel_y1 = cropbox.y1 - pdf_max_y
        rel_y2 = cropbox.y1 - pdf_min_y
        
        # 5. Crop Rect
        x_min = rel_x1 - padding
        y_min = rel_y1 - padding
        x_max = rel_x2 + padding
        y_max = rel_y2 + padding
        
        clip_rect = fitz.Rect(x_min, y_min, x_max, y_max)
        final_rect = clip_rect & page.rect
        
        if final_rect.is_empty or final_rect.width < 1 or final_rect.height < 1:
            skipped += 1
            if original_rot != 0: page.set_rotation(original_rot)
            continue
            
        # 6. Save
        pix = page.get_pixmap(matrix=mat, clip=final_rect)
        filename = f"shape_{shape_id}_inst_{instance_id}.png"
        filepath = os.path.join(output_dir, filename)
        pix.save(filepath)
        
        if original_rot != 0: page.set_rotation(original_rot)
        
        count += 1
        if count % 100 == 0:
            print(f"  Cropped {count}...")

    print(f"✓ Successfully cropped {count} images to '{output_dir}/'")
    print(f"  (Skipped {skipped} instances)")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--json', required=True)
    parser.add_argument('--output', default='crops')
    parser.add_argument('--padding', type=int, default=10)
    parser.add_argument('--dpi', type=int, default=150)
    args = parser.parse_args()
    
    crop_shapes(args.pdf, args.json, args.output, args.padding, args.dpi)

if __name__ == "__main__":
    main()
