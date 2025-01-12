import cv2
import numpy as np
import time
from datetime import datetime
import base64
import json
import asyncio
import websockets
import threading

################################################################################
#                       ASYNC WEBSOCKET CLIENT CODE                            #
################################################################################

# Global variable for storing an open WebSocket connection
ws_connection = None

async def connect_to_backend(uri="ws://localhost:8000/feed"):
    """
    Connect to the FastAPI WebSocket backend and keep the connection open.
    We'll listen for messages and print them. This function runs forever
    until the program exits.
    """
    global ws_connection
    print(f"[WS] Attempting to connect to {uri}...")

    async with websockets.connect(uri) as websocket:
        ws_connection = websocket
        print("[WS] WebSocket connection established.")

        # Keep listening for messages from the server
        try:
            while True:
                message = await websocket.recv()  # blocks until a message arrives
                # Handle incoming messages (JSON from the server)
                print(f"[WS] Received from server: {message}")
        except websockets.exceptions.ConnectionClosedError:
            print("[WS] Connection closed by the server.")
        except Exception as e:
            print(f"[WS] Error in receive loop: {e}")

    # If we exit the async with block, the connection is closed
    ws_connection = None
    print("[WS] WebSocket connection closed.")

async def send_frame_to_backend(frame, goal="explore the city"):
    """
    Send a single frame + goal to the backend via the open WebSocket connection.
    """
    global ws_connection
    if not ws_connection:
        print("[WS] No active WebSocket connection. Cannot send frame.")
        return

    # 1) Encode frame as JPEG in memory
    success, buffer = cv2.imencode(".jpg", frame)
    if not success:
        print("[WS] Failed to encode frame as JPEG.")
        return

    # 2) Convert to base64
    image_bytes = buffer.tobytes()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # 3) Build JSON message
    message = {
        "goal": goal,
        "image": image_b64
    }
    # 4) Send JSON message
    try:
        await ws_connection.send(json.dumps(message))
        print("[WS] Frame + goal sent to backend.")
    except Exception as e:
        print(f"[WS] Error sending frame: {e}")

def start_websocket_client():
    """
    Start the background thread that runs an asyncio event loop.
    It connects to the WebSocket server and keeps listening/receiving.
    """
    loop = asyncio.new_event_loop()

    def run_loop_forever():
        asyncio.set_event_loop(loop)
        # The connect_to_backend() call will block forever in an async sense
        loop.run_until_complete(connect_to_backend("ws://localhost:8000/feed"))

    # Launch a daemon thread for the event loop
    t = threading.Thread(target=run_loop_forever, daemon=True)
    t.start()

def send_frame_in_thread(frame, goal="explore the city"):
    """
    Thread-safe helper to schedule the 'send_frame_to_backend' coroutine
    on the already‐running event loop. 
    """
    loop = asyncio.get_event_loop()
    # If there's no current running event loop, it means
    # we are in the main thread; let's find the existing loop in threads.
    if loop.is_running():
        # We are inside the event loop or the event loop is already running
        asyncio.run_coroutine_threadsafe(send_frame_to_backend(frame, goal), loop)
    else:
        # This can happen if we call it from the main thread outside an async context
        # but our background thread is running the loop:
        # get_event_loop() might raise an error if no loop is set. 
        # In that case, we find the running loop from threading.
        import threading
        for th in threading.enumerate():
            if th.name == "MainThread":
                # Not always trivial to forcibly get the loop from that thread.
                pass
        # simpler fallback: just try the default loop
        asyncio.run_coroutine_threadsafe(send_frame_to_backend(frame, goal), asyncio.get_event_loop())

################################################################################
#                        OPEN CV CAPTURE CODE                                  #
################################################################################

def setup_video_capture(device_id=1):
    """
    Set up video capture from the Skydroid receiver.
    Try different device_id values (0, 1, 2...) if not detected.
    """
    cap = cv2.VideoCapture(device_id)
    
    if not cap.isOpened():
        raise ValueError(f"Failed to open video device {device_id}")
    
    # Adjust these if needed
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
    # 1) Start our background WebSocket client thread
    start_websocket_client()

    try:
        # 2) Initialize video capture
        cap = setup_video_capture()
        print("Video capture started. Press 'q' to quit, 's' to save a frame, 'u' to send a frame.")

        while True:
            frame = capture_frame(cap)
            
            # Display the frame
            cv2.imshow('Drone Video Feed', frame)

            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                # Quit
                break
            elif key == ord('s'):
                # Save a frame locally
                filename = save_frame(frame)
                print(f"Saved frame to {filename}")
            elif key == ord('u'):
                # **NEW**: Send a frame (plus the default goal) to the backend
                print("Sending frame to backend...")
                send_frame_in_thread(frame, goal="explore the city")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'cap' in locals():
            cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
