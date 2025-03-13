from operate.config import Config
from PIL import Image, ImageDraw, ImageFont
import os
import base64
import io
from datetime import datetime
import time

# Load configuration
config = Config()


def create_annotated_ocr_image(result, image_path, search_text=None, start_text=None, end_text=None):
    """
    Creates an image with all OCR detected text elements annotated with indices.
    
    Args:
        result (list): The list of results returned by EasyOCR.
        image_path (str): Path to the original image.
        search_text (str, optional): Text being searched for in a click operation.
        start_text (str, optional): Starting text for drag operation.
        end_text (str, optional): Ending text for drag operation.
        
    Returns:
        tuple: (annotated_image_path, base64_encoded_image)
    """
    # Create /ocr directory if it doesn't exist
    ocr_dir = "ocr"
    if not os.path.exists(ocr_dir):
        os.makedirs(ocr_dir)

    # Open the original image
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)
    
    # Try to use a default font
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 20)
        except:
            font = ImageFont.load_default()
    
    # Draw all text elements with their indices
    for index, element in enumerate(result):
        text = element[1]
        box = element[0]
        
        # Calculate bounding box
        min_x = min([coord[0] for coord in box])
        max_x = max([coord[0] for coord in box])
        min_y = min([coord[1] for coord in box])
        max_y = max([coord[1] for coord in box])
        
        # Draw rectangle around text
        draw.rectangle([(min_x, min_y), (max_x, max_y)], outline="blue", width=2)
        
        # Draw index number
        draw.text((min_x, min_y - 20), f"#{index}: {text[:20]}", fill="blue", font=font)
        
        # Highlight search text, start text, or end text if provided
        if (search_text and search_text in text) or (start_text and start_text in text) or (end_text and end_text in text):
            draw.rectangle([(min_x, min_y), (max_x, max_y)], outline="red", width=3)
            
    # Save the image with bounding boxes
    datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    annotated_image_path = os.path.join(ocr_dir, f"ocr_annotated_{datetime_str}.png")
    image.save(annotated_image_path)
    
    # Convert to base64 for sending to LLM
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    if config.verbose:
        print(f"[create_annotated_ocr_image] OCR annotated image saved at: {annotated_image_path}")
    
    return annotated_image_path, img_base64


def ask_llm_for_text_index_with_retry(client, result, search_text, annotated_image_base64, max_retries=3):
    """
    Asks the LLM to identify the correct index for a text element with retry logic.
    
    Args:
        client: The initialized LLM client
        result (list): The list of results returned by EasyOCR
        search_text (str): The text to search for
        annotated_image_base64 (str): Base64 encoded annotated image
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        int: The index of the text element identified by the LLM
    """
    # Create a list of text elements with their indices
    text_elements = []
    for i, element in enumerate(result):
        text_elements.append(f"#{i}: {element[1]}")
    
    text_elements_str = "\n".join(text_elements)
    
    # Create the prompt for the LLM
    prompt = f"""
    I need to identify the correct text element to interact with on this screen.
    
    I'm looking for: "{search_text}"
    
    Here are all the text elements detected on the screen (with their indices):
    {text_elements_str}
    
    Look at the annotated image where each text element is marked with its index.
    Which index number (just the number) contains the text I'm looking for?
    If there are multiple matches, choose the one that appears to be the most relevant UI element (like a button, link, or menu item).
    
    Return ONLY the index number, nothing else.
    """
    
    retries = 0
    while retries < max_retries:
        try:
            # Send the request to the LLM
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that identifies UI elements in screenshots."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{annotated_image_base64}"}}
                    ]}
                ],
                temperature=0.1,
                max_tokens=10  # We only need a short response
            )
            
            # Extract the index from the response
            index_str = response.choices[0].message.content.strip()
            
            # Clean up the response to get just the number
            index_str = ''.join(c for c in index_str if c.isdigit())
            
            if not index_str:
                raise ValueError("LLM did not return a valid index number")
            
            return int(index_str)
            
        except Exception as e:
            retries += 1
            if config.verbose:
                print(f"[ask_llm_for_text_index_with_retry] Attempt {retries} failed: {e}")
            
            if retries >= max_retries:
                if config.verbose:
                    print(f"[ask_llm_for_text_index_with_retry] All {max_retries} attempts failed")
                raise
            
            # Wait before retrying (exponential backoff)
            time.sleep(2 ** retries)
    
    # This should never be reached due to the raise in the loop
    raise Exception("Failed to get valid index from LLM after retries")


def ask_llm_for_best_match_with_retry(client, result, search_text, annotated_image_base64, max_retries=3):
    """
    Asks the LLM to find the best matching text element when exact search text is not found.
    
    Args:
        client: The initialized LLM client
        result (list): The list of results returned by EasyOCR
        search_text (str): The text that was searched for but not found exactly
        annotated_image_base64 (str): Base64 encoded annotated image
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        int or None: The index of the best matching text element identified by the LLM,
                    or None if no suitable match is found
    """
    # Create a list of text elements with their indices
    text_elements = []
    for i, element in enumerate(result):
        text_elements.append(f"#{i}: {element[1]}")
    
    text_elements_str = "\n".join(text_elements)
    
    # Create the prompt for the LLM
    prompt = f"""
    I need to find the best matching text element on this screen.
    
    I was looking for: "{search_text}" but couldn't find an exact match.
    
    Here are all the text elements detected on the screen (with their indices):
    {text_elements_str}
    
    Look at the annotated image where each text element is marked with its index.
    Which index number (just the number) contains text that best matches what I'm looking for?
    
    Consider semantic similarity, partial matches, or UI elements that might serve the same purpose.
    
    If you don't see ANY reasonable match, respond with "NONE".
    Otherwise, return ONLY the index number of the best match.
    """
    
    retries = 0
    while retries < max_retries:
        try:
            # Send the request to the LLM
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that identifies UI elements in screenshots. You only respond with a number or NONE."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{annotated_image_base64}"}}
                    ]}
                ],
                temperature=0.1,
                max_tokens=10  # We only need a short response
            )
            
            # Extract the response
            response_text = response.choices[0].message.content.strip()
            
            # Check if the LLM found no match
            if response_text.upper() == "NONE":
                if config.verbose:
                    print(f"[ask_llm_for_best_match_with_retry] LLM found no suitable match")
                return None
            
            # Clean up the response to get just the number
            index_str = ''.join(c for c in response_text if c.isdigit())
            
            if not index_str:
                raise ValueError("LLM did not return a valid index number")
            
            selected_index = int(index_str)
            
            # Verify the selected index is valid
            if selected_index >= len(result):
                raise ValueError(f"LLM returned invalid index {selected_index}")
                
            if config.verbose:
                print(f"[ask_llm_for_best_match_with_retry] LLM selected index: {selected_index} with text: '{result[selected_index][1]}'")
                
            return selected_index
            
        except Exception as e:
            retries += 1
            if config.verbose:
                print(f"[ask_llm_for_best_match_with_retry] Attempt {retries} failed: {e}")
            
            if retries >= max_retries:
                if config.verbose:
                    print(f"[ask_llm_for_best_match_with_retry] All {max_retries} attempts failed")
                return None
            
            # Wait before retrying (exponential backoff)
            time.sleep(2 ** retries)
    
    # This should never be reached due to the return None in the loop
    return None


def get_text_element(result, search_text, image_path, client=None):
    """
    Searches for a text element in the OCR results and returns its index.
    If multiple matches are found and a client is provided, uses LLM to select the best one.
    If no exact match is found and a client is provided, uses LLM to find the best approximate match.
    
    Args:
        result (list): The list of results returned by EasyOCR.
        search_text (str): The text to search for in the OCR results.
        image_path (str): Path to the original image.
        client (optional): OpenAI client for LLM assistance if multiple matches are found.

    Returns:
        int: The index of the element containing the search text.

    Raises:
        Exception: If the text element is not found in the results and no alternative can be found.
    """
    if config.verbose:
        print("[get_text_element]")
        print("[get_text_element] search_text", search_text)

    # Find all matching indices
    matching_indices = []
    for index, element in enumerate(result):
        text = element[1]
        if search_text in text:
            matching_indices.append(index)
            if config.verbose:
                print("[get_text_element][loop] found search_text, index:", index)

    # If we have matches, process them
    if matching_indices:
        # If we have only one match or no client, return the first match
        if len(matching_indices) == 1 or client is None:
            return matching_indices[0]
        
        # If we have multiple matches and a client, use LLM to select the best one
        try:
            # Create annotated image with all text elements
            _, annotated_image_base64 = create_annotated_ocr_image(
                result, image_path, search_text=search_text
            )
            
            # Ask LLM to identify the correct index with retry logic
            selected_index = ask_llm_for_text_index_with_retry(
                client, result, search_text, annotated_image_base64
            )
            
            if config.verbose:
                print(f"[get_text_element] LLM selected index: {selected_index}")
            
            # Verify the selected index is valid
            if selected_index >= len(result):
                if config.verbose:
                    print(f"[get_text_element] LLM selected invalid index {selected_index}, falling back to first match")
                return matching_indices[0]
            
            # Verify the selected text contains the search text
            selected_text = result[selected_index][1]
            if search_text not in selected_text:
                if config.verbose:
                    print(f"[get_text_element] LLM selected index {selected_index} with text '{selected_text}' which doesn't contain '{search_text}', falling back to first match")
                return matching_indices[0]
            
            return selected_index
            
        except Exception as e:
            if config.verbose:
                print(f"[get_text_element] Error in LLM selection: {e}")
                print(f"[get_text_element] Falling back to first match: {matching_indices[0]}")
            return matching_indices[0]
    
    # No exact matches found
    if client is None:
        # Without a client, we can't find alternatives
        raise Exception(f"The text element '{search_text}' was not found in the image")
    
    # With a client, try to find the best approximate match
    if config.verbose:
        print(f"[get_text_element] No exact match found for '{search_text}', asking LLM for best match")
    
    try:
        # Create annotated image with all text elements
        _, annotated_image_base64 = create_annotated_ocr_image(
            result, image_path
        )
        
        # Ask LLM to find the best match
        best_match_index = ask_llm_for_best_match_with_retry(
            client, result, search_text, annotated_image_base64
        )
        
        if best_match_index is not None:
            if config.verbose:
                print(f"[get_text_element] LLM found best match at index {best_match_index}: '{result[best_match_index][1]}'")
            return best_match_index
        
        # If LLM couldn't find a match either
        raise Exception(f"The text element '{search_text}' was not found in the image and no suitable alternative could be identified")
        
    except Exception as e:
        if config.verbose:
            print(f"[get_text_element] Error in LLM best match selection: {e}")
        raise Exception(f"The text element '{search_text}' was not found in the image: {str(e)}")


def get_text_coordinates(result, index, image_path):
    """
    Gets the coordinates of the text element at the specified index as a percentage of screen width and height.
    Args:
        result (list): The list of results returned by EasyOCR.
        index (int): The index of the text element in the results list.
        image_path (str): Path to the screenshot image.

    Returns:
        dict: A dictionary containing the 'x' and 'y' coordinates as percentages of the screen width and height.
    """
    if index >= len(result):
        raise Exception("Index out of range in OCR results")

    # Get the bounding box of the text element
    bounding_box = result[index][0]

    # Calculate the center of the bounding box
    min_x = min([coord[0] for coord in bounding_box])
    max_x = max([coord[0] for coord in bounding_box])
    min_y = min([coord[1] for coord in bounding_box])
    max_y = max([coord[1] for coord in bounding_box])

    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    # Get image dimensions
    with Image.open(image_path) as img:
        width, height = img.size

    # Convert to percentages
    percent_x = round((center_x / width), 3)
    percent_y = round((center_y / height), 3)

    return {"x": percent_x, "y": percent_y}


def ask_llm_for_drag_drop_indices_with_retry(client, result, start_text, end_text, annotated_image_base64, max_retries=3):
    """
    Asks the LLM to identify the correct indices for drag and drop operation with retry logic.
    
    Args:
        client: The initialized LLM client
        result (list): The list of results returned by EasyOCR
        start_text (str): The text at the starting point
        end_text (str): The text at the ending point
        annotated_image_base64 (str): Base64 encoded annotated image
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        tuple: (start_index, end_index) identified by the LLM
    """
    # Create a list of text elements with their indices
    text_elements = []
    for i, element in enumerate(result):
        text_elements.append(f"#{i}: {element[1]}")
    
    text_elements_str = "\n".join(text_elements)
    
    # Create the prompt for the LLM
    prompt = f"""
    I need to identify the correct text elements for a drag and drop operation on this screen.
    
    I need to drag from: "{start_text}"
    And drop onto: "{end_text}"
    
    Here are all the text elements detected on the screen (with their indices):
    {text_elements_str}
    
    Look at the annotated image where each text element is marked with its index.
    Which index number contains the starting text, and which index number contains the ending text?
    
    Return ONLY the two index numbers separated by a comma, like this: "3,7"
    """
    
    retries = 0
    while retries < max_retries:
        try:
            # Send the request to the LLM
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that identifies UI elements in screenshots."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{annotated_image_base64}"}}
                    ]}
                ],
                temperature=0.1,
                max_tokens=10  # We only need a short response
            )
            
            # Extract the indices from the response
            indices_str = response.choices[0].message.content.strip()
            
            # Parse the response to get the two indices
            parts = indices_str.split(',')
            if len(parts) != 2:
                raise ValueError(f"LLM did not return two indices separated by comma: {indices_str}")
                
            start_index = int(''.join(c for c in parts[0] if c.isdigit()))
            end_index = int(''.join(c for c in parts[1] if c.isdigit()))
            
            return start_index, end_index
            
        except Exception as e:
            retries += 1
            if config.verbose:
                print(f"[ask_llm_for_drag_drop_indices_with_retry] Attempt {retries} failed: {e}")
            
            if retries >= max_retries:
                if config.verbose:
                    print(f"[ask_llm_for_drag_drop_indices_with_retry] All {max_retries} attempts failed")
                raise
            
            # Wait before retrying (exponential backoff)
            time.sleep(2 ** retries)
    
    # This should never be reached due to the raise in the loop
    raise Exception("Failed to get valid indices from LLM after retries")


def get_drag_drop_text_coordinates(result, start_text, end_text, image_path, client=None):
    """
    Gets the coordinates for a drag and drop operation between two text elements.
    If multiple matches are found, uses LLM to select the best ones.
    
    Args:
        result (list): The list of results returned by EasyOCR.
        start_text (str): The text at the starting point.
        end_text (str): The text at the ending point.
        image_path (str): Path to the screenshot image.
        client (optional): OpenAI client for LLM assistance if multiple matches are found.
        
    Returns:
        dict: A dictionary containing start_x, start_y, end_x, end_y as percentages.
    """
    # Find all matching indices
    start_indices = []
    end_indices = []
    
    for index, element in enumerate(result):
        text = element[1]
        
        if start_text in text:
            start_indices.append(index)
            
        if end_text in text:
            end_indices.append(index)
    
    if not start_indices:
        raise Exception(f"Could not find start text element: '{start_text}'")
    
    if not end_indices:
        raise Exception(f"Could not find end text element: '{end_text}'")
    
    # If we have multiple matches and a client is provided, use LLM to select the best ones
    start_index = start_indices[0]  # Default to first match
    end_index = end_indices[0]      # Default to first match
    
    if (len(start_indices) > 1 or len(end_indices) > 1) and client:
        try:
            # Create annotated image with all text elements
            annotated_image_path, img_base64 = create_annotated_ocr_image(
                result, image_path, start_text=start_text, end_text=end_text
            )
            
            # Ask LLM to identify the correct indices with retry logic
            start_index, end_index = ask_llm_for_drag_drop_indices_with_retry(
                client, result, start_text, end_text, img_base64
            )
            
            if config.verbose:
                print(f"[get_drag_drop_text_coordinates] LLM selected indices: {start_index}, {end_index}")
            
            # Verify the indices are valid
            if start_index >= len(result) or end_index >= len(result):
                if config.verbose:
                    print(f"[get_drag_drop_text_coordinates] LLM selected invalid indices {start_index}, {end_index}, falling back to first matches")
                start_index = start_indices[0]
                end_index = end_indices[0]
            
            # Verify the selected texts contain the search texts
            start_selected_text = result[start_index][1]
            end_selected_text = result[end_index][1]
            
            if start_text not in start_selected_text or end_text not in end_selected_text:
                if config.verbose:
                    print(f"[get_drag_drop_text_coordinates] LLM selected texts don't match search criteria, falling back to first matches")
                start_index = start_indices[0]
                end_index = end_indices[0]
        
        except Exception as e:
            if config.verbose:
                print(f"[get_drag_drop_text_coordinates] Error in LLM selection: {e}")
                print(f"[get_drag_drop_text_coordinates] Falling back to first matches: {start_index}, {end_index}")
    
    # Get the bounding boxes
    start_box = result[start_index][0]
    end_box = result[end_index][0]
    
    # Calculate the centers
    start_min_x = min([coord[0] for coord in start_box])
    start_max_x = max([coord[0] for coord in start_box])
    start_min_y = min([coord[1] for coord in start_box])
    start_max_y = max([coord[1] for coord in start_box])
    
    end_min_x = min([coord[0] for coord in end_box])
    end_max_x = max([coord[0] for coord in end_box])
    end_min_y = min([coord[1] for coord in end_box])
    end_max_y = max([coord[1] for coord in end_box])
    
    start_center_x = (start_min_x + start_max_x) / 2
    start_center_y = (start_min_y + start_max_y) / 2
    
    end_center_x = (end_min_x + end_max_x) / 2
    end_center_y = (end_min_y + end_max_y) / 2
    
    # Get image dimensions
    with Image.open(image_path) as img:
        width, height = img.size
    
    # Convert to percentages
    start_percent_x = round((start_center_x / width), 3)
    start_percent_y = round((start_center_y / height), 3)
    end_percent_x = round((end_center_x / width), 3)
    end_percent_y = round((end_center_y / height), 3)
    
    return {
        "start_x": start_percent_x,
        "start_y": start_percent_y,
        "end_x": end_percent_x,
        "end_y": end_percent_y
    }
