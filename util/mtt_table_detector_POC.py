from transformers import TableTransformerForObjectDetection, AutoProcessor
from PIL import Image
import torch
from PIL import ImageDraw, ImageFont
import os

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


# Create output folder
output_dir = os.path.join("logs", "table_detections_POC")
os.makedirs(output_dir, exist_ok=True)

# Draw image
drawn_image = image.copy()
draw = ImageDraw.Draw(drawn_image)

# Optional: specify a default font if available (platform dependent)
try:
    font = ImageFont.truetype("arial.ttf", 14)
except:
    font = ImageFont.load_default()

COLOR_PALETTE = [
    "red", "green", "blue", "orange", "purple",
    "cyan", "magenta", "yellow", "lime", "pink"
]


# Show results
for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
    if model.config.id2label[label.item()] == "table":
        print(f"Table detected with score {score:.3f} at {box.tolist()}")
        label_str = model.config.id2label[label.item()]
        score_val = round(score.item(), 2)
        xmin, ymin, xmax, ymax = box.tolist()

        # Define a basic color palette for up to 10 unique labels (extendable)


        # Compute color by label index (wrap around if more labels than colors)
        color = COLOR_PALETTE[label.item() % len(COLOR_PALETTE)]

        # Draw rectangle
        draw.rectangle([xmin, ymin, xmax, ymax], outline=color, width=2)

        # Label text
        label_text = f"{label_str} ({score_val})"
        draw.text((xmin + 5, ymin + 5), label_text, fill=color, font=font)

    # Save image to file with page number
    page_number = 13
    output_path = os.path.join(output_dir, f"test.png")
    drawn_image.save(output_path)