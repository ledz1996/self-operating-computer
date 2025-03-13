import io
import base64
import json
import os
import time
import asyncio
from PIL import Image, ImageDraw


def validate_and_extract_image_data(data):
    if not data or "messages" not in data:
        raise ValueError("Invalid request, no messages found")

    messages = data["messages"]
    if (
        not messages
        or not isinstance(messages, list)
        or not messages[-1].get("image_url")
    ):
        raise ValueError("No image provided or incorrect format")

    image_data = messages[-1]["image_url"]["url"]
    if not image_data.startswith("data:image"):
        raise ValueError("Invalid image format")

    return image_data.split("base64,")[-1], messages


def get_label_coordinates(label, label_coordinates):
    """
    Retrieves the coordinates for a given label.

    :param label: The label to find coordinates for (e.g., "~1").
    :param label_coordinates: Dictionary containing labels and their coordinates.
    :return: Coordinates of the label or None if the label is not found.
    """
    return label_coordinates.get(label)


def is_overlapping(box1, box2):
    x1_box1, y1_box1, x2_box1, y2_box1 = box1
    x1_box2, y1_box2, x2_box2, y2_box2 = box2

    # Check if there is no overlap
    if x1_box1 > x2_box2 or x1_box2 > x2_box1:
        return False
    if (
        y1_box1 > y2_box2 or y1_box2 > y2_box1
    ):  # Adjusted to check 100px proximity above
        return False

    return True


def add_labels(base64_data, yolo_model):
    image_bytes = base64.b64decode(base64_data)
    image_labeled = Image.open(io.BytesIO(image_bytes))  # Corrected this line
    image_debug = image_labeled.copy()  # Create a copy for the debug image
    image_original = (
        image_labeled.copy()
    )  # Copy of the original image for base64 return

    results = yolo_model(image_labeled)

    draw = ImageDraw.Draw(image_labeled)
    debug_draw = ImageDraw.Draw(
        image_debug
    )  # Create a separate draw object for the debug image
    font_size = 45

    labeled_images_dir = "labeled_images"
    label_coordinates = {}  # Dictionary to store coordinates

    if not os.path.exists(labeled_images_dir):
        os.makedirs(labeled_images_dir)

    counter = 0
    drawn_boxes = []  # List to keep track of boxes already drawn
    for result in results:
        if hasattr(result, "boxes"):
            for det in result.boxes:
                bbox = det.xyxy[0]
                x1, y1, x2, y2 = bbox.tolist()

                debug_label = "D_" + str(counter)
                debug_index_position = (x1, y1 - font_size)
                debug_draw.rectangle([(x1, y1), (x2, y2)], outline="blue", width=1)
                debug_draw.text(
                    debug_index_position,
                    debug_label,
                    fill="blue",
                    font_size=font_size,
                )

                overlap = any(
                    is_overlapping((x1, y1, x2, y2), box) for box in drawn_boxes
                )

                if not overlap:
                    draw.rectangle([(x1, y1), (x2, y2)], outline="red", width=1)
                    label = "~" + str(counter)
                    index_position = (x1, y1 - font_size)
                    draw.text(
                        index_position,
                        label,
                        fill="red",
                        font_size=font_size,
                    )

                    # Add the non-overlapping box to the drawn_boxes list
                    drawn_boxes.append((x1, y1, x2, y2))
                    label_coordinates[label] = (x1, y1, x2, y2)

                    counter += 1

    # Save the image
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    output_path = os.path.join(labeled_images_dir, f"img_{timestamp}_labeled.png")
    output_path_debug = os.path.join(labeled_images_dir, f"img_{timestamp}_debug.png")
    output_path_original = os.path.join(
        labeled_images_dir, f"img_{timestamp}_original.png"
    )

    image_labeled.save(output_path)
    image_debug.save(output_path_debug)
    image_original.save(output_path_original)

    buffered_original = io.BytesIO()
    image_original.save(buffered_original, format="PNG")  # I guess this is needed
    img_base64_original = base64.b64encode(buffered_original.getvalue()).decode("utf-8")

    # Convert image to base64 for return
    buffered_labeled = io.BytesIO()
    image_labeled.save(buffered_labeled, format="PNG")  # I guess this is needed
    with open("labeled_image.png", "wb") as f:
        f.write(buffered_labeled.getvalue())
    img_base64_labeled = base64.b64encode(buffered_labeled.getvalue()).decode("utf-8")

    return img_base64_labeled, label_coordinates


def get_click_position_in_percent(coordinates, image_size):
    """
    Calculates the click position at the center of the bounding box and converts it to percentages.

    :param coordinates: A tuple of the bounding box coordinates (x1, y1, x2, y2).
    :param image_size: A tuple of the image dimensions (width, height).
    :return: A tuple of the click position in percentages (x_percent, y_percent).
    """
    if not coordinates or not image_size:
        return None

    # Calculate the center of the bounding box
    x_center = (coordinates[0] + coordinates[2]) / 2
    y_center = (coordinates[1] + coordinates[3]) / 2

    # Convert to percentages
    x_percent = x_center / image_size[0]
    y_percent = y_center / image_size[1]

    return x_percent, y_percent


def get_drag_drop_positions(start_label, end_label, label_coordinates, image_size):
    """
    Gets the start and end positions for a drag and drop operation using label IDs.
    
    Args:
        start_label (str): The label ID for the starting element.
        end_label (str): The label ID for the ending element.
        label_coordinates (dict): Dictionary mapping label IDs to their coordinates.
        image_size (tuple): A tuple of the image dimensions (width, height).
        
    Returns:
        tuple: A tuple containing (start_x, start_y, end_x, end_y) as percentages.
    """
    if start_label not in label_coordinates or end_label not in label_coordinates:
        return None
    
    start_coords = label_coordinates[start_label]
    end_coords = label_coordinates[end_label]
    
    # Calculate the centers of the bounding boxes
    start_x_center = (start_coords[0] + start_coords[2]) / 2
    start_y_center = (start_coords[1] + start_coords[3]) / 2
    
    end_x_center = (end_coords[0] + end_coords[2]) / 2
    end_y_center = (end_coords[1] + end_coords[3]) / 2
    
    # Convert to percentages
    start_x_percent = start_x_center / image_size[0]
    start_y_percent = start_y_center / image_size[1]
    end_x_percent = end_x_center / image_size[0]
    end_y_percent = end_y_center / image_size[1]
    
    return start_x_percent, start_y_percent, end_x_percent, end_y_percent
