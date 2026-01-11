"""
OCR Processor STEP 2.5 (Captions on images)
=========================================

- Test to run various models via ollama on the cropped shape images.
- Generates a descriptive caption (Geometry + Text).
- Saves ONLY 'moondream_caption' and 'ocr_has_text' (boolean).
- Removes legacy 'ocr_text' field.

Usage:
    python run_ocr_llm.py --json step1_with_markers.json --crops crops/
"""

import argparse
import json
import os
import ollama

def run_moondream_pipeline(json_path, crops_dir, output_path):
    print(f"Loading JSON from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)
        
    total = len(data['instances'])
    print(f"Running Moondream on {total} instances...\n")
    
    for i, instance in enumerate(data['instances']):
        shape_id = instance['shape_id']
        instance_id = instance.get('instance_id', i+1)
        
        filename = f"shape_{shape_id}_inst_{instance_id}.png"
        filepath = os.path.join(crops_dir, filename)
        
        caption = ""
        
        if os.path.exists(filepath):
            try:
                response = ollama.chat(
                    model='bakllava',
                    messages=[{
                        'role': 'user',
                        'content': 'What do you see?',
                        'images': [filepath]
                    }]
                )
                caption = response['message']['content'].strip()
                if not caption: caption = "[Empty Response]"
            except Exception as e:
                caption = f"Error: {str(e)}"
        else:
            caption = "[File Not Found]"

        # Console Output
        display = (caption[:60] + '..') if len(caption) > 60 else caption
        print(f"[{i+1}/{total}] {filename} -> {display}")

        # Update JSON Fields
        instance['moondream_caption'] = caption
        instance['ocr_has_text'] = not caption.startswith("[") and "no text" not in caption.lower()
        
        # REMOVE Legacy Field if it exists
        if 'ocr_text' in instance:
            del instance['ocr_text']

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
        
    print(f"\n✓ Saved to {output_path}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', required=True)
    parser.add_argument('--crops', required=True)
    parser.add_argument('--output', default='step2_ocr_llm.json')
    args = parser.parse_args()
    
    run_moondream_pipeline(args.json, args.crops, args.output)
