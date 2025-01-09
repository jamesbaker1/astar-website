import cv2
import numpy as np
import time
from datetime import datetime

def setup_video_capture(device_id=1):
    """
    Set up video capture from the Skydroid receiver.
    Try different device_id values (0, 1, 2...) if the receiver isn't detected.
    """
    cap = cv2.VideoCapture(device_id)
    
    if not cap.isOpened():
        raise ValueError(f"Failed to open video device {device_id}")
    
    # You may need to adjust these parameters based on your receiver's output
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    return cap

def capture_frame(cap):
    """Capture a single frame from the video stream."""
    ret, frame = cap.read()
    if not ret:
        raise RuntimeError("Failed to capture frame")
    return frame

def save_frame(frame, output_dir="captured_frames"):
    """Save a frame to disk with timestamp."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{output_dir}/frame_{timestamp}.jpg"
    cv2.imwrite(filename, frame)
    return filename

def main():
    try:
        # Initialize video capture
        cap = setup_video_capture()
        
        print("Video capture started. Press 'q' to quit, 's' to save a frame.")
        
        while True:
            frame = capture_frame(cap)
            
            # Display the frame
            cv2.imshow('Drone Video Feed', frame)
            
            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                filename = save_frame(frame)
                print(f"Saved frame to {filename}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'cap' in locals():
            cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()