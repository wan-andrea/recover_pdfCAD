"""
PDF Marker Detector STEP 1.5
============================

Takes the output from step1 (JSON + original PDF) and searches for text markers
(BT...ET blocks) near each detected shape. Updates the JSON with marker flags.

Outputs an updated PDF with:
  - RED boxes for annotation markers
  - BLUE boxes for graphic blocks

Usage:
    python detect_markers.py --pdf example1.pdf --input step1.json --output step1_with_markers.json --output-pdf step1_marked.pdf
"""

import re
import argparse
import json
import sys
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, DecodedStreamObject, ArrayObject


# ------------------------------------------------------------------------------
# TEXT EXTRACTION
# ------------------------------------------------------------------------------

def extract_text_blocks_from_page(page):
    """
    Extracts all BT...ET text blocks from a page's content stream.
    Returns a list of dicts with: {raw, bbox_estimate, has_text_operators}
    """
    if "/Contents" not in page:
        return []
    
    contents = page["/Contents"]
    if not isinstance(contents, ArrayObject):
        contents = ArrayObject([contents])
    
    text_blocks = []
    
    for stream_ref in contents:
        data = stream_ref.get_object().get_data()
        try:
            text = data.decode('latin-1')
        except:
            continue
        
        # Find all BT...ET blocks
        bt_et_pattern = re.compile(r'(BT\s+)(.*?)(\s+ET)', re.DOTALL)
        matches = bt_et_pattern.findall(text)
        
        for prefix, content, suffix in matches:
            full_block = prefix + content + suffix
            
            # Check for text operators
            has_text = bool(re.search(r'\b(Tj|TJ)\b|[\'"]', content))
            
            # Try to extract text position (Tm or Td operators give x,y)
            position = extract_text_position(content)
            
            text_blocks.append({
                'raw': full_block,
                'content': content,
                'position': position,
                'has_text_operators': has_text
            })
    
    return text_blocks


def extract_text_position(bt_content):
    """
    Extracts approximate x,y position from BT...ET content.
    Looks for Tm (text matrix) or Td (text delta) operators.
    """
    # Tm: a b c d e f Tm (last 2 are x, y)
    tm_match = re.search(r'([\d.\-]+)\s+([\d.\-]+)\s+Tm', bt_content)
    if tm_match:
        try:
            return (float(tm_match.group(1)), float(tm_match.group(2)))
        except:
            pass
    
    # Td: tx ty Td
    td_match = re.search(r'([\d.\-]+)\s+([\d.\-]+)\s+Td', bt_content)
    if td_match:
        try:
            return (float(td_match.group(1)), float(td_match.group(2)))
        except:
            pass
    
    return None


# ------------------------------------------------------------------------------
# SPATIAL PROXIMITY
# ------------------------------------------------------------------------------

def transform_point(x, y, matrix):
    """
    Applies 2D affine transformation matrix [a, b, c, d, e, f] to point (x, y).
    Result: x' = a*x + c*y + e, y' = b*x + d*y + f
    """
    a, b, c, d, e, f = matrix
    x_prime = a * x + c * y + e
    y_prime = b * x + d * y + f
    return (x_prime, y_prime)


def bbox_center(bbox):
    """Returns center point of bbox [minx, miny, maxx, maxy]."""
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def distance(p1, p2):
    """Euclidean distance between two points."""
    return ((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)**0.5


def find_nearest_text_block(shape_instance, text_blocks, threshold=100):
    """
    Finds the nearest text block to a shape instance.
    """
    bbox = shape_instance['bbox_local']
    matrix = shape_instance['transform_matrix']
    
    local_center = bbox_center(bbox)
    page_center = transform_point(local_center[0], local_center[1], matrix)
    
    nearest = None
    min_dist = float('inf')
    
    for tb in text_blocks:
        if tb['position'] is None:
            continue
        
        dist = distance(page_center, tb['position'])
        if dist < min_dist and dist < threshold:
            min_dist = dist
            nearest = tb
    
    return (nearest, min_dist) if nearest else (None, None)


# ------------------------------------------------------------------------------
# PDF GENERATION WITH COLOR-CODED BOXES
# ------------------------------------------------------------------------------

def generate_marked_pdf(pdf_path, json_path, output_pdf_path):
    """
    Reads the original PDF and JSON with marker data,
    draws colored boxes (RED for markers, BLUE for graphics),
    writes new PDF.
    """
    print(f"Loading JSON from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    print(f"Loading PDF from {pdf_path}...")
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    
    # Group instances by page
    instances_by_page = {}
    for instance in data['instances']:
        page_num = instance['page']
        if page_num not in instances_by_page:
            instances_by_page[page_num] = []
        instances_by_page[page_num].append(instance)
    
    print("Generating marked PDF...")
    for page_num, page in enumerate(reader.pages, 1):
        print(f"  Processing page {page_num}...")
        
        # Get instances on this page
        page_instances = instances_by_page.get(page_num, [])
        
        # Add bounding boxes
        if page_instances and "/Contents" in page:
            contents = page["/Contents"]
            is_array = isinstance(contents, ArrayObject)
            stream_list = contents if is_array else ArrayObject([contents])
            
            new_stream_list = ArrayObject()
            
            for stream_ref in stream_list:
                original_stream = stream_ref.get_object()
                data_bytes = original_stream.get_data()
                try:
                    text = data_bytes.decode('latin-1')
                except:
                    new_stream_list.append(stream_ref)
                    continue
                
                # Append boxes to end of stream (before any existing Q)
                box_commands = ""
                
                for instance in page_instances:
                    bbox = instance['bbox_local']
                    matrix = instance['transform_matrix']
                    is_marker = instance.get('is_predicted_annotation_marker', False)
                    
                    # Color: RED for markers, BLUE for graphics
                    if is_marker:
                        r, g, b = 1.0, 0.0, 0.0  # RED
                    else:
                        r, g, b = 0.0, 0.0, 1.0  # BLUE
                    
                    # Transform bbox corners
                    min_x, min_y, max_x, max_y = bbox
                    w = max_x - min_x
                    h = max_y - min_y
                    pad = 0.5
                    
                    # Bottom-left corner
                    x1, y1 = transform_point(min_x - pad, min_y - pad, matrix)
                    # Top-right corner
                    x2, y2 = transform_point(max_x + pad, max_y + pad, matrix)
                    
                    # Ensure min/max order
                    x_min, x_max = min(x1, x2), max(x1, x2)
                    y_min, y_max = min(y1, y2), max(y1, y2)
                    
                    width = x_max - x_min
                    height = y_max - y_min
                    
                    box_cmd = (
                        f" q "
                        f"{r:.3f} {g:.3f} {b:.3f} RG 1.5 w "
                        f"{x_min:.2f} {y_min:.2f} {width:.2f} {height:.2f} re S "
                        f"Q "
                    )
                    box_commands += box_cmd
                
                # Append to stream
                modified_text = text + box_commands
                
                new_stream = DecodedStreamObject()
                new_stream.set_data(modified_text.encode('latin-1'))
                new_stream_list.append(writer._add_object(new_stream))
            
            # Assign back
            if is_array:
                page[NameObject("/Contents")] = new_stream_list
            else:
                if len(new_stream_list) > 0:
                    page[NameObject("/Contents")] = new_stream_list[0]
        
        # Compress if possible
        if hasattr(page, 'compress_content_streams'):
            try:
                page.compress_content_streams()
            except:
                pass
        
        writer.add_page(page)
    
    # Write output PDF
    with open(output_pdf_path, 'wb') as f:
        writer.write(f)
    print(f"✓ Saved marked PDF to {output_pdf_path}")


# ------------------------------------------------------------------------------
# MAIN PIPELINE
# ------------------------------------------------------------------------------

def detect_markers(pdf_path, json_input_path, json_output_path, output_pdf_path, proximity_threshold=100):
    """
    Main function: Load JSON, extract text blocks from PDF, match them, update JSON.
    """
    print(f"Loading JSON from {json_input_path}...")
    with open(json_input_path, 'r') as f:
        data = json.load(f)
    
    print(f"Loading PDF from {pdf_path}...")
    reader = PdfReader(pdf_path)
    
    # Extract text blocks per page
    page_text_blocks = {}
    for i, page in enumerate(reader.pages):
        print(f"  Extracting text from page {i+1}...")
        page_text_blocks[i+1] = extract_text_blocks_from_page(page)
    
    # Process each instance
    print("Matching text blocks to shape instances...")
    marker_count = 0
    
    for instance in data['instances']:
        page_num = instance['page']
        text_blocks = page_text_blocks.get(page_num, [])
        
        # Find nearest text
        nearest_text, dist = find_nearest_text_block(instance, text_blocks, proximity_threshold)
        
        if nearest_text and nearest_text['has_text_operators']:
            instance['is_predicted_annotation_marker'] = True
            instance['marker_text_raw'] = nearest_text['content']
            instance['marker_distance'] = round(dist, 2)
            marker_count += 1
        else:
            instance['is_predicted_annotation_marker'] = False
            instance['marker_text_raw'] = None
            instance['marker_distance'] = None
    
    # Update shape definitions
    shape_marker_flags = {}
    for instance in data['instances']:
        shape_id = str(instance['shape_id'])
        if instance['is_predicted_annotation_marker']:
            shape_marker_flags[shape_id] = True
    
    for shape_id, shape_def in data['shape_definitions'].items():
        is_marker = shape_marker_flags.get(shape_id, False)
        shape_def['is_predicted_annotation_marker'] = is_marker
        if is_marker:
            shape_def['semantic_label'] = 'Annotation Marker'
        else:
            shape_def['semantic_label'] = 'Graphic Block'
    
    # Save updated JSON
    with open(json_output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Detected {marker_count} annotation markers out of {len(data['instances'])} instances.")
    print(f"✓ Saved updated JSON to {json_output_path}")
    
    # Generate marked PDF
    if output_pdf_path:
        generate_marked_pdf(pdf_path, json_output_path, output_pdf_path)


def main():
    parser = argparse.ArgumentParser(description="Detect text markers near shapes in PDF.")
    parser.add_argument('--pdf', default='example1.pdf', help="Original PDF file")
    parser.add_argument('--input', default='step1.json', help="Input JSON from step 1")
    parser.add_argument('--output', default='step1_with_markers.json', help="Output JSON with markers")
    parser.add_argument('--output-pdf', default='step1_marked.pdf', help="Output PDF with colored boxes")
    parser.add_argument('--threshold', type=float, default=100, help="Max distance (page units) to match text to shape")
    
    args = parser.parse_args()
    
    try:
        detect_markers(args.pdf, args.input, args.output, args.output_pdf, args.threshold)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
