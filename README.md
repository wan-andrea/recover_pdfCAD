# recover_pdfCAD
A computer vision and spatial analysis pipeline for extracting, clustering, and visualizing semantic geometry from vector-based PDF architectural drawings.

In simple terms: Can we recover CAD blocks in vector graphics PDFs of architectural drawings by looking at the drawing commands encoded in the PDF as a text file?

The primary motivation for this work is to avoid the loss of precision and high computational overhead associated with traditional Computer Vision methods. Standard approaches typically rasterize high-fidelity vector drawings into pixel grids and then employ heavy deep learning models—such as **CNNs** or **ViTs**—to probabilistic "guess" where objects are located.

By parsing the **drawing instructions** directly, this project treats the problem as a deterministic text-parsing task rather than a stochastic vision task.

## 📂 Repository Structure

<pre>
rawpdfcad/
│   ├── example1.pdf           # Input file
│   ├── process_cad.py         # Step 1: Vector extraction
│   ├── find_groups.py         # Step 2: Spatial clustering
│   └── visualize_groups.py    # Step 3: Visualization
</pre>

## 🚀 Installation
Prerequisites: Ensure you have Anaconda or Miniconda installed.

Create Environment:
```conda env create -f environment.yml```
Activate:
```conda activate recover_pdfCAD```
Deactivate:
```conda deactivate```

## 🛠 Usage Pipeline
Navigate to the experiment directory to run the scripts on your data.

### Step 1: Raw Vector Extraction
Parses the PDF content stream to identify repeating vector shapes (CAD blocks) and extracts them into a normalized registry.

```python scripts/process_pdf_cad.py --input sample_inputs/example2.pdf --output test_outputs/step1.pdf --json test_outputs/step1.json```
Note: Replace ```example2.pdf``` with the file you want to run on.

### Step 1.5: Marker Association (Optional)
I provide an optional tool for debugging. It looks for text entities near the extracted shapes. Shapes with text near them are predicted as annotation markers. It's not failproof, but it's a good first step towards classification.

```python scripts/detect_markers.py --pdf sample_inputs/example2.pdf --input test_outputs/step1.json --output test_outputs/step1_markers.json --output-pdf test_outputs/step1_marked.pdf```

### Step 1.75: Shape Cropping
Extracts high-resolution images of every unique shape instance, accounting for PDF coordinate systems and rotation.

```python scripts/crop_shapes.py --pdf sample_inputs/example2.pdf --json test_outputs/step1_markers.json --output test_outputs/crops/```

### Step 2: Spatial Clustering
Analyzes the shape registry to find "constellations" of shapes that appear in fixed relative positions (e.g., a chair always appearing 50 units from a desk).

```python scripts/find_groups.py --input test_outputs/step1.json --output test_outputs/step2.json```

### Step 2.5: Semantic Captioning
Passes the cropped images to a local Vision-Language Model (VLM) to generate descriptions.
Note: This code *runs* but is very much WIP. Results are unusable; requires further prompt engineering.
```python scripts/run_ocr.py --json test_outputs/step1_markers.json --crops test_outputs/crops/ --output test_outputs/step2_ocr.json```


### Step 3: Visualization
Generates a new PDF overlaying the detected spatial groups with color-coded bounding boxes for verification.
```python scripts/visualize_groups.py --input sample_inputs/example2.pdf --data test_outputs/step1.json --groups test_outputs/step2.json --output test_outputs/step3.pdf ```

## 🧠 Methodology
This prototype bypasses traditional raster-based Computer Vision (CNNs/YOLO) in favor of analyzing the raw PostScript-like vector commands hidden within the PDF stream.

### 1. Text-Based Vector Parsing (Step 1)
Instead of "seeing" pixels, the script treats the PDF content stream as a raw text file. It utilizes Regex to parse the drawing commands:
*   **Pattern Matching**: It identifies sequences of "move to" (`m`), "line to" (`l`), and "curve" (`c`) commands that repeat exactly across the file.
*   **Normalization**: The script strips whitespace to ensure that identical shapes are matched even if formatting varies slightly.
*   **Extraction**: Rather than redrawing the shapes, we extract the transformation matrix (`cm`) associated with each block to determine its global coordinates.

**Output:** `step1.json`
A flat registry of every repeating vector shape found on every page.

```json
{
  "metadata": {
    "total_instances": 150,
    "unique_shapes": 12
  },
  "shape_definitions": {
    "1": { 
      "count": 45, 
      "color_rgb": [0.2, 0.8, 0.2] 
    }
  },
  "instances": [
    {
      "instance_id": 1,
      "page": 1,
      "shape_id": 1,
      "bbox_local": ,
      "transform_matrix": [1.0, 0.0, 0.0, 1.0, 100.0, 200.0],
      "snippet_raw": "..."
    }
  ]
}
```

### 2. Spatial Graph Clustering (Step 2)
Once individual shapes (e.g., a chair, a monitor) are identified, we use unsupervised clustering to find higher-order groups (e.g., a workstation).
*   **KD-Tree Indexing**: We feed the centroids of all detected shapes into a KD-Tree to efficiently query neighbors within a specific `SEARCH_RADIUS` (bounding box threshold).
*   **Relative Signatures**: We do not look for absolute coordinates. We look for **repeating relative vectors**. If "Shape A" is consistently found at vector `(50, 20)` relative to "Shape B", this relationship is recorded as a "strong connection."
*   **Graph Traversal**: These strong connections form a graph. Connected components within this graph are extracted as "Groups" (e.g., Cubicle Type A).

Output: step2_groups.json
A hierarchical list of detected groups (clusters) and their definitions.
``` json
{
  "group_definitions": {
    "1": {
      "composition":,     // List of shape_ids in this group[1][2][3]
      "semantic_label": "Cubicle Type A",
      "count": 10
    }
  },
  "group_instances": [
    {
      "group_type_id": 1,
      "page": 1,
      "centroid_avg": [125.0, 225.0],
      "members": ,   // References instance_ids from Step 1
      "member_shapes":[2][3][1]
    }
  ]
}
```

### 3. Critical Assumptions (CAD/BIM Workflows)
This approach relies on specific behaviors of AEC software (AutoCAD, Revit, Rhino) when printing to PDF:
*   **Instancing vs. Redrawing**: We assume the source software uses "Blocks" (AutoCAD) or "Families" (Revit). When these are printed to PDF, efficient drivers will output the drawing commands *once* and use transformation matrices to place copies. 
    *   *Success Case*: A furniture plan where chairs are copied, or blocks are used.
    *   *Failure Case*: Sometimes, drawings can appear visually identical, but are actually manually redrawn, or joined. In this case, the PDF stream contains unique coordinates for every line, and the text-pattern matching will fail to find repeats.
*   **Vector Content**: The input PDF must be vector-based (generated from CAD software), not a raster scan of a paper drawing.

### 4. Export Recommendations for AutoCAD
*   **Use `DWG To PDF.pc3`**: The standard Autodesk driver is reliable for this purpose.
*   **Do Not Explode**: Keep blocks intact in the DWG before plotting. Avoid "PDF Optimizer" or "Reduce file size" scripts, as they can flatten the coordinate systems to save bytes, destroying the recurring patterns. 
*   **Avoid Flattening**: Flattening layers or content streams can sometimes bake transformations.
*   **Precision**: Increase vector resolution (DPI) if shapes are being rounded/distorted.