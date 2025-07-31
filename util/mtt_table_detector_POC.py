from transformers import TableTransformerForObjectDetection, AutoProcessor
from PIL import Image
import torch

# Load model and processor
processor = AutoProcessor.from_pretrained("microsoft/table-transformer-detection")
model = TableTransformerForObjectDetection.from_pretrained("microsoft/table-transformer-detection")
model.eval()

# Load image (rendered PDF page)
image = Image.open("page_13.jpg").convert("RGB")  # replace with your image path

# Prepare input
inputs = processor(images=image, return_tensors="pt")

# Inference
with torch.no_grad():
    outputs = model(**inputs)

# Post-process
target_size = torch.tensor([image.size[::-1]])  # (height, width)
results = processor.post_process_object_detection(outputs, target_sizes=target_size, threshold=0.8)[0]

# Show results
for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
    if model.config.id2label[label.item()] == "table":
        print(f"Table detected with score {score:.3f} at {box.tolist()}")
