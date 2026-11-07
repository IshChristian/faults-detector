# Model Training Guide

## 0. Licensing first
Models we deploy for paying customers must have a licence that allows closed-source commercial use.

| Use | Default |
|---|---|
| General people/vehicle detection | Frigate's bundled SSDLite MobileNet (Apache-2.0) via OpenVINO |
| Custom fault classes | **RF-DETR Nano/Small/Medium** (Apache-2.0, code and weights) |
| Experiments / benchmarks only | Ultralytics YOLO (AGPL-3.0). Not deployable to customers without an Ultralytics Enterprise licence |

Record `architecture` and `license` on every model you register. The platform blocks activation of non-commercial licences.

## 1. Choose fault classes
Start with 2–5 classes only.

- Football: `player`, `referee`, `goalkeeper`, `ball`.
- Restaurant: `staff`, `customer`, `fire`, `smoke`, `dirty_table`.
- Factory: `leak`, `smoke`, `guard`, `person`.
- Screens: usually no detector needed. Black, frozen and OCR checks are rule-based (see `08-rules-and-actions.md`).

## 2. Collect data
For each class:
- Minimum: 150–300 images. Better: 500–1,000.
- Include day, night, crowds, different angles and lighting, and **hard negatives** (things the model confuses with the fault: steam vs smoke, wet floor vs leak).
- Split by **time or camera**, not randomly, so near-duplicate frames don't end up in both train and val.

Sources:
- Frigate snapshots and event clips (sample 1 frame per 1–2 s).
- Events marked `false_positive` or `wrong_class` by operators (exported automatically as hard negatives).
- Customer footage, with written permission recorded in the customer agreement.
- Public datasets whose licence allows commercial use.
- Your own phone recordings.

## 3. Label data
Start Label Studio (`docker compose --profile labeling up -d`) and open `http://localhost:8080`.

1. Create an object-detection project with your classes.
2. Label bounding boxes. Two people label 10% of images to check consistency.
3. Export as **COCO** (used by RF-DETR) or **YOLO** (for Ultralytics experiments).

RF-DETR dataset layout (COCO):

```text
datasets/kitchen-safety-v1/
├── train/   _annotations.coco.json + images
├── valid/   _annotations.coco.json + images
└── test/    _annotations.coco.json + images
```

## 4. Train (RF-DETR)

Locally (CPU is fine only for smoke tests):

```bash
pip install rfdetr
```

```python
from rfdetr import RFDETRNano

model = RFDETRNano()
model.train(
    dataset_dir="datasets/kitchen-safety-v1",
    epochs=50,
    batch_size=8,
    grad_accum_steps=2,
    output_dir="models/kitchen-safety-v1",
)
```

## 5. Train free on Google Colab
Colab's free tier gives a GPU, but sessions have usage and idle limits. Write checkpoints to Google Drive so a disconnect doesn't lose progress.

```python
!pip install -q rfdetr
from google.colab import drive
drive.mount('/content/drive')

from rfdetr import RFDETRNano
model = RFDETRNano()
model.train(
    dataset_dir="/content/drive/MyDrive/datasets/kitchen-safety-v1",
    epochs=50, batch_size=16,
    output_dir="/content/drive/MyDrive/models/kitchen-safety-v1",
)
```

## 6. Evaluate
Report on the held-out **test** split, plus a 1-hour replay of real site footage:

| Metric | Launch target |
|---|---|
| mAP@0.5 (clear fault classes) | ≥ 0.75 |
| Precision | ≥ 0.80 |
| Recall | ≥ 0.75 |
| False alarms in replay | < 5 per camera per hour |
| Inference latency on target hardware | Fits the camera's detect fps |

Store the results in `metrics.json` next to the weights and upload them with the model.

## 7. Export and deploy
1. Export to ONNX:
   ```python
   model = RFDETRNano(pretrain_weights="models/kitchen-safety-v1/checkpoint_best_total.pth")
   model.export()   # writes an .onnx file in the output directory
   ```
2. Upload through the dashboard (Training Studio → Upload model) with `architecture=rf-detr-n` and `license=Apache-2.0`.
3. Run **Test model** against recent footage, then approve it.
4. Activate it for specific cameras. Rollback is one click.

**Running inside Frigate vs the vision worker:** Frigate loads one detector model per instance. If a custom model replaces Frigate's general detector, it must also detect `person`. Otherwise run the custom model in the VisionGuard vision worker on Frigate's restreamed sub-stream, and keep Frigate on the general model. Check the Frigate docs for your pinned version to confirm which ONNX model types its detectors accept.

## 8. Improve after launch
1. Review false positives weekly (Fault Center → filter `false_positive`).
2. Export the feedback-labelled frames into the next dataset version.
3. Retrain.
4. Compare the new model with the active one on the **same** test split and replay footage.
5. Activate only if precision and recall don't regress.
