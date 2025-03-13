import pyautogui
import platform
import time
import math

from operate.utils.misc import convert_percent_to_decimal


class OperatingSystem:
    def write(self, content):
        try:
            content = content.replace("\\n", "\n")
            for char in content:
                pyautogui.write(char)
        except Exception as e:
            print("[OperatingSystem][write] error:", e)

    def press(self, keys):
        try:
            for key in keys:
                pyautogui.keyDown(key)
            time.sleep(0.1)
            for key in keys:
                pyautogui.keyUp(key)
        except Exception as e:
            print("[OperatingSystem][press] error:", e)

    def mouse(self, click_detail):
        try:
            x = convert_percent_to_decimal(click_detail.get("x"))
            y = convert_percent_to_decimal(click_detail.get("y"))
            button = click_detail.get("button", "left")  # Default to left click if not specified

            if click_detail and isinstance(x, float) and isinstance(y, float):
                self.click_at_percentage(x, y, button=button)

        except Exception as e:
            print("[OperatingSystem][mouse] error:", e)

    def click_at_percentage(
        self,
        x_percentage,
        y_percentage,
        duration=0.2,
        circle_radius=50,
        circle_duration=0.5,
        button="left",
    ):
        try:
            screen_width, screen_height = pyautogui.size()
            x_pixel = int(screen_width * float(x_percentage))
            y_pixel = int(screen_height * float(y_percentage))

            pyautogui.moveTo(x_pixel, y_pixel, duration=duration)

            start_time = time.time()
            while time.time() - start_time < circle_duration:
                angle = ((time.time() - start_time) / circle_duration) * 2 * math.pi
                x = x_pixel + math.cos(angle) * circle_radius
                y = y_pixel + math.sin(angle) * circle_radius
                pyautogui.moveTo(x, y, duration=0.1)

            pyautogui.click(x_pixel, y_pixel, button=button)
        except Exception as e:
            print("[OperatingSystem][click_at_percentage] error:", e)
            
    def drag_and_drop(self, start_x, start_y, end_x, end_y, duration=0.5):
        """
        Performs a drag and drop operation from start coordinates to end coordinates.
        
        Args:
            start_x (float): Starting x-coordinate as percentage of screen width
            start_y (float): Starting y-coordinate as percentage of screen height
            end_x (float): Ending x-coordinate as percentage of screen width
            end_y (float): Ending y-coordinate as percentage of screen height
            duration (float): Duration of the drag operation in seconds
        """
        try:
            screen_width, screen_height = pyautogui.size()
            
            # Convert percentages to pixels
            start_x_pixel = int(screen_width * float(start_x))
            start_y_pixel = int(screen_height * float(start_y))
            end_x_pixel = int(screen_width * float(end_x))
            end_y_pixel = int(screen_height * float(end_y))
            
            # Move to start position
            pyautogui.moveTo(start_x_pixel, start_y_pixel, duration=0.2)
            
            # Perform drag and drop
            pyautogui.dragTo(end_x_pixel, end_y_pixel, duration, button='left')
            
        except Exception as e:
            print("[OperatingSystem][drag_and_drop] error:", e)
