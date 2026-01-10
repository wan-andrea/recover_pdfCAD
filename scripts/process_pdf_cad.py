"""
PDF Shape Analyzer & Visualizer STEP 1
===============================

Analyzes a PDF to identify repeated geometric vector shapes (CAD blocks).
Outputs:
1. A visual PDF with colored bounding boxes around detected shapes. (output_visualized.pdf)
2. A JSON registry mapping shape IDs to their instances, coordinates, and raw drawing code. (output_data.json)

Usage:
    python process_pdf_cad.py --input raw.pdf --output labeled.pdf --json data.json
"""

import re
import random
import colorsys
import argparse
import json
import sys
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, DecodedStreamObject, ArrayObject

# ------------------------------------------------------------------------------
# CONFIGURATION & UTILS
# ------------------------------------------------------------------------------

def generate_distinct_colors(n):
    colors = []
    for i in range(n):
        hue = i / n
        sat = 0.95
        val = 0.9
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        colors.append((r, g, b))
    return colors

def normalize_snippet(snippet):
    """Normalize whitespace for consistent comparison."""
    return ' '.join(snippet.split())

def parse_transform_matrix(matrix_str):
    """Extracts the 6 numbers from a 'a b c d e f cm' string."""
    nums = re.findall(r'([0-9.\-]+)', matrix_str)
    # Usually the last 6 numbers before 'cm'
    if len(nums) >= 6:
        return [float(x) for x in nums[-6:]]
    return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

def get_bounding_box(snippet):
    """Parses drawing commands to find local min/max X and Y."""
    x_coords, y_coords = [], []
    
    # Points (m, l)
    points = re.findall(r'([0-9.\-]+)\s+([0-9.\-]+)\s+[ml]', snippet)
    for p in points: 
        x_coords.append(float(p[0])); y_coords.append(float(p[1]))
    
    # Curves (c)
    curves = re.findall(r'([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+c', snippet)
    for c in curves: 
        vals = list(map(float, c))
        x_coords.extend(vals[0::2]); y_coords.extend(vals[1::2])
    
    # Rectangles (re)
    rects = re.findall(r'([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+re', snippet)
    for r in rects: 
        x, y, w, h = map(float, r)
        x_coords.extend([x, x+w]); y_coords.extend([y, y+h])
    
    if not x_coords: return None
    return (min(x_coords), min(y_coords), max(x_coords), max(y_coords))

def is_shape_closed(snippet):
    """
    Determines if a PDF path is closed based on standard operators.
    
    Operators that close a path:
    - h: Close current subpath (straight line to start)
    - re: Append rectangle (always closed)
    - f, F, f*: Fill path (implies closure)
    - b, B, b*, B*: Fill and stroke (implies closure)
    - s: Close and stroke (equivalent to h S)
    """
    # Normalize simply to check presence of tokens
    tokens = snippet.split()
    
    # 1. Explicit Close Operator 'h'
    if 'h' in tokens:
        return True
        
    # 2. Rectangle 're' is always a closed shape
    if 're' in tokens:
        return True
        
    # 3. Path Painting Operators that imply closure
    # 's' = close and stroke
    # 'f', 'F', 'f*' = fill (implies closing)
    # 'b', 'B', 'b*', 'B*' = close, fill, stroke
    closing_painters = {'s', 'f', 'F', 'f*', 'b', 'B', 'b*', 'B*'}
    
    # Check if the snippet ends with or contains a closing painter
    # We look at the last few tokens usually, but for a "snippet" that might be a 
    # composite path, presence anywhere is a strong indicator of at least one closed loop.
    # However, strictly speaking, a path is defined, then painted.
    
    # Let's check if any token matches our closing painters
    if any(t in closing_painters for t in tokens):
        return True
        
    return False

# ------------------------------------------------------------------------------
# CORE LOGIC
# ------------------------------------------------------------------------------

def analyze_global_shapes(reader):
    """
    Pass 1: Scan ALL pages to build a global registry of repeated shapes.
    Returns:
        global_registry (dict): { normalized_snippet: { 'id': int, 'count': int, 'color': (r,g,b), 'is_closed': bool } }
    """
    print("Pass 1: Analyzing global shape frequencies...")
    
    # Pattern to find: q [matrix] cm [drawing] Q
    pattern = re.compile(r'(q\s+(?:[0-9.\-]+\s+){6}cm\s+)(.*?)(\s+Q)', re.DOTALL)
    
    snippet_counts = {} # Norm -> Count
    snippet_raw_map = {} # Norm -> One example of raw snippet (for analysis)

    for i, page in enumerate(reader.pages):
        if "/Contents" not in page: continue
        
        contents = page["/Contents"]
        if not isinstance(contents, ArrayObject): contents = ArrayObject([contents])
        
        for stream_ref in contents:
            data = stream_ref.get_object().get_data()
            try:
                text = data.decode('latin-1')
            except:
                continue
                
            matches = pattern.findall(text)
            for _, snippet, _ in matches:
                norm = normalize_snippet(snippet)
                snippet_counts[norm] = snippet_counts.get(norm, 0) + 1
                if norm not in snippet_raw_map:
                    snippet_raw_map[norm] = snippet

    # Filter for repeats
    repeated_snippets = [s for s, c in snippet_counts.items() if c > 1]
    
    # Build Registry
    colors = generate_distinct_colors(len(repeated_snippets))
    random.shuffle(colors)
    
    global_registry = {}
    for idx, norm in enumerate(repeated_snippets):
        raw_snippet = snippet_raw_map[norm]
        global_registry[norm] = {
            'id': idx + 1,
            'count': snippet_counts[norm],
            'color': colors[idx],
            'is_closed': is_shape_closed(raw_snippet)
        }
        
    print(f"  Found {len(repeated_snippets)} unique shapes that repeat globally.")
    return global_registry

def process_and_export(reader, writer, global_registry, bbox_only_mode):
    """
    Pass 2: Rewrite PDF content and build JSON instance list.
    """
    print("Pass 2: Generating PDF and JSON...")
    
    pattern = re.compile(r'(q\s+(?:[0-9.\-]+\s+){6}cm\s+)(.*?)(\s+Q)', re.DOTALL)
    
    # Data containers for JSON output
    json_instances = []
    instance_counter = 1
    
    for page_num, page in enumerate(reader.pages):
        print(f"  Processing Page {page_num + 1}...")
        
        if "/Contents" in page:
            contents = page["/Contents"]
            # Standardize to list
            is_array = isinstance(contents, ArrayObject)
            stream_list = contents if is_array else ArrayObject([contents])
            
            new_stream_list = ArrayObject()
            
            for stream_ref in stream_list:
                original_stream = stream_ref.get_object()
                data = original_stream.get_data()
                try:
                    text = data.decode('latin-1')
                except:
                    new_stream_list.append(stream_ref)
                    continue
                
                # We need to replace text using matches, BUT also record data.
                # Regex substitution doesn't easily let us extract side-data to a list.
                # So we use a manual Find-Iterate-Replace approach or a closure.
                
                # We'll use a closure to capture side-effects (adding to json_instances)
                def replacement_handler(match):
                    nonlocal instance_counter
                    
                    prefix = match.group(1) # q ... cm
                    snippet = match.group(2) # drawing
                    suffix = match.group(3) # Q
                    
                    norm = normalize_snippet(snippet)
                    
                    if norm in global_registry:
                        meta = global_registry[norm]
                        shape_id = meta['id']
                        color = meta['color']
                        
                        # 1. Capture Data for JSON
                        bbox = get_bounding_box(snippet)
                        matrix = parse_transform_matrix(prefix)
                        
                        if bbox:
                            instance_data = {
                                "instance_id": instance_counter,
                                "page": page_num + 1,
                                "shape_id": shape_id,
                                "bbox_local": list(bbox), # [minx, miny, maxx, maxy]
                                "transform_matrix": matrix, # [a, b, c, d, e, f]
                                "snippet_raw": snippet, # Raw drawing commands
                            }
                            json_instances.append(instance_data)
                            instance_counter += 1
                            
                            # 2. Rewrite PDF Stream
                            r, g, b = color
                            min_x, min_y, max_x, max_y = bbox
                            w = max_x - min_x
                            h = max_y - min_y
                            pad = 0.5
                            
                            bbox_cmd = (
                                f" q "
                                f"{r:.3f} {g:.3f} {b:.3f} RG 2 w "
                                f"{min_x-pad:.2f} {min_y-pad:.2f} {w+pad*2:.2f} {h+pad*2:.2f} re S "
                                f"Q "
                            )
                            
                            if bbox_only_mode:
                                return f"{prefix}\n{bbox_cmd}{suffix}"
                            else:
                                return f"{prefix}{snippet}\n{bbox_cmd}{suffix}"
                                
                    return match.group(0)

                # Execute replacement
                modified_text = pattern.sub(replacement_handler, text)
                
                # Create new stream object
                new_stream = DecodedStreamObject()
                new_stream.set_data(modified_text.encode('latin-1'))
                
                # Add to writer
                new_stream_list.append(writer._add_object(new_stream))

            # Assign modified streams back to page
            if is_array:
                page[NameObject("/Contents")] = new_stream_list
            else:
                if len(new_stream_list) > 0:
                    page[NameObject("/Contents")] = new_stream_list[0]

        # Compress if possible
        if hasattr(page, 'compress_content_streams'):
            try: page.compress_content_streams()
            except: pass
            
        writer.add_page(page)

    return json_instances

# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract shapes to JSON and Colorize PDF.")
    parser.add_argument('--input', default='example1.pdf', help="Input PDF")
    parser.add_argument('--output', default='output_visualized.pdf', help="Output PDF")
    parser.add_argument('--json', default='output_data.json', help="Output JSON map")
    parser.add_argument('--bbox-only', action='store_true', help="Hide original shapes")
    
    args = parser.parse_args()
    
    print(f"Opening {args.input}...")
    try:
        reader = PdfReader(args.input)
        writer = PdfWriter()
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return

    # Pass 1: Global Analysis
    global_registry = analyze_global_shapes(reader)
    
    # Pass 2: Generation & Extraction
    instances = process_and_export(reader, writer, global_registry, args.bbox_only)
    
    # Write PDF
    with open(args.output, 'wb') as f:
        writer.write(f)
    print(f"Saved PDF to: {args.output}")
    
    # Build Final JSON Structure
    # Map registry format to desired output format
    shape_definitions = {}
    for norm, meta in global_registry.items():
        shape_definitions[str(meta['id'])] = {
            "semantic_label": "", # Placeholder for user to fill later
            "count": meta['count'],
            "color_rgb": meta['color'],
            "is_closed": meta['is_closed']
        }
    
    final_json = {
        "metadata": {
            "source_file": args.input,
            "total_instances": len(instances),
            "unique_shapes": len(shape_definitions)
        },
        "shape_definitions": shape_definitions,
        "instances": instances
    }
    
    # Write JSON
    with open(args.json, 'w') as f:
        json.dump(final_json, f, indent=2)
    print(f"Saved JSON to: {args.json}")

if __name__ == "__main__":
    main()
