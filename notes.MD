# process_pdf_cad.py
The original script that parses text to find repeated geometries
```python process_pdf_cad.py --input example2.pdf --output temp/ex2_1.pdf --json temp/ex2_1.json```

# detect_markers.py
Geometries which have text near them are markers
```python detect_markers.py --pdf example2.pdf --input temp/ex2_1.json --output ex2_2.json --output-pdf ex2_2.pdf```

# crop_shapes.py
detect_markers uses regex so it's not failproof, so instead let's use a vision model to double check
```python crop_shapes.py --pdf example2.pdf --json temp/ex2_2.json --output temp/crops/```

# find_groups.py
Groups of clustered shapes together usually suggest CAD blocks.
```python find_groups.py --input temp/ex2_2.json --output temp/ex2_3.json```

# visualize_groups.py
Given the json created in find_groups, let's visualize it in the PDF.
```python visualize_groups.py --input example2.pdf --data temp/ex2_2.json --groups temp/ex2_3.json --output ex2_3.pdf```
