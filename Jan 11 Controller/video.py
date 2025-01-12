# video.py
import cv2
import numpy as np
from threading import Thread, Lock
from queue import Queue
import time

# ---- NEW IMPORT ----
try:
    from ultralytics import YOLOWorld
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("Warning: ultralytics is not installed. YOLO features will be unavailable.")

class VisualizationType:
    """Enum for different visualization types"""
    NONE = 0
    YOLO = 1
    OPTICAL_FLOW = 2
    ALL = 3

class VideoManager:
    def __init__(self, device_id=1, buffer_size=5):
        self.device_id = device_id
        self.camera = None
        self.running = False
        self.display_active = False
        self.subscribers = []
        self.visualization_type = VisualizationType.NONE
        
        # Overlays
        self.overlay_lock = Lock()
        self.flow_overlay = None
        self.yolo_overlay = None  # store YOLO results here

        # For frame retrieval
        self.frame_lock = Lock()
        self.latest_frame = None

        # Debug
        self.debug = True

        # If ultralytics is installed, load YOLO model
        if YOLO_AVAILABLE:
            # Initialize a YOLO-World model
            self.model = YOLOWorld("yolov8s-world.pt")  # pick any variant
            # Define custom classes (optional)
            self.model.set_classes(["person", "bus"])
            if self.debug:
                print("YOLOWorld model loaded successfully.")
        else:
            self.model = None

    def start(self):
        """Start video capture with simpler display loop"""
        try:
            print(f"Attempting to open video device {self.device_id}")
            self.camera = cv2.VideoCapture(self.device_id)
            
            # Set camera parameters
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            if not self.camera.isOpened():
                raise ValueError(f"Failed to open video device {self.device_id}")
            
            self.running = True
            # For this demo, we assume we always want to display
            self.display_active = True

            # Run the display in the main thread
            self._run_display_loop()
            return True
            
        except Exception as e:
            print(f"Error starting video manager: {str(e)}")
            self.stop()
            return False

    def stop(self):
        """Stop video capture"""
        self.running = False
        self.display_active = False
        if self.camera:
            self.camera.release()
        cv2.destroyAllWindows()
        print("Video manager stopped")

    def list_available_cameras(self):
        """List all available video devices"""
        available_devices = []
        for i in range(10):  # Check first 10 indices
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    print(f"Found working device at index {i}")
                    print(f"Resolution: {frame.shape}")
                    print(f"Backend: {cap.getBackendName()}")
                    print(f"FPS: {cap.get(cv2.CAP_PROP_FPS)}")
                    print("---")
                cap.release()

    def get_frame(self):
        """Get the latest frame"""
        with self.frame_lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def set_visualization(self, viz_type):
        """Set the visualization type"""
        with self.overlay_lock:
            self.visualization_type = viz_type

    def subscribe(self, callback):
        """Subscribe to receive frames"""
        self.subscribers.append(callback)
        if self.debug:
            print(f"Added new subscriber, total subscribers: {len(self.subscribers)}")

    def unsubscribe(self, callback):
        """Remove a frame subscriber"""
        if callback in self.subscribers:
            self.subscribers.remove(callback)
            if self.debug:
                print(f"Removed subscriber, remaining subscribers: {len(self.subscribers)}")

    def update_yolo_overlay(self, detections):
        """Update YOLO detection overlay"""
        with self.overlay_lock:
            self.yolo_overlay = detections

    def update_flow_overlay(self, flow_vectors, z_movement=None):
        """Update optical flow overlay"""
        with self.overlay_lock:
            self.flow_overlay = (flow_vectors, z_movement)

    def _apply_yolo_overlay(self, frame):
        """Apply YOLO detection boxes to frame"""
        if self.yolo_overlay is None:
            return frame

        overlay = frame.copy()
        for label, confidence, (x, y, w, h) in self.yolo_overlay:
            # Draw bounding box
            cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 255, 0), 2)
            # Draw label
            text = f"{label}: {confidence:.2f}"
            cv2.putText(overlay, text, (x, y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        return overlay

    def _apply_flow_overlay(self, frame):
        """Apply optical flow visualization to frame"""
        if self.flow_overlay is None:
            return frame

        overlay = frame.copy()
        flow_vectors, z_movement = self.flow_overlay

        # Draw flow vectors
        for vector in flow_vectors:
            x, y = vector[0]
            dx, dy = vector[1]
            cv2.arrowedLine(overlay, 
                            (int(x), int(y)), 
                            (int(x + dx), int(y + dy)),
                            (0, 255, 0), 2)

        return overlay

    def _run_display_loop(self):
        """Simple display loop similar to your working code"""
        print("Starting display loop")
        
        while self.running:
            ret, frame = self.camera.read()
            if not ret or frame is None:
                continue

            # Store the latest frame for external use (get_frame)
            with self.frame_lock:
                self.latest_frame = frame.copy()
            
            # -----------------------------
            # 1. Run YOLO inference if requested
            # -----------------------------
            if (
                self.model 
                and self.visualization_type in [VisualizationType.YOLO, VisualizationType.ALL]
            ):
                # Run prediction on the current frame (BGR -> model handles internally)
                results = self.model.predict(frame, verbose=False)

                # If results come back successfully, parse them
                if len(results) > 0:
                    detection_info = []
                    # Each 'results' item can contain multiple boxes
                    for r in results:
                        for box in r.boxes:
                            # box.xyxy, box.xywh, box.conf, box.cls, etc.
                            x1, y1, x2, y2 = box.xyxy[0]  # bounding box corners
                            conf = float(box.conf[0])     # confidence
                            cls_id = int(box.cls[0])      # class ID
                            
                            # If you defined custom classes with .set_classes(), 
                            # then model.names[cls_id] gives the correct label
                            label = self.model.names[cls_id] if self.model.names else f"class_{cls_id}"
                            
                            w = x2 - x1
                            h = y2 - y1
                            detection_info.append(
                                (label, conf, (int(x1), int(y1), int(w), int(h)))
                            )
                    # Update the YOLO overlay
                    self.update_yolo_overlay(detection_info)
                else:
                    # If no results, clear the overlay
                    self.update_yolo_overlay(None)

            # -----------------------------
            # 2. Prepare display frame (apply overlays)
            # -----------------------------
            display_frame = frame.copy()

            # Apply YOLO boxes if YOLO or ALL is active
            if self.visualization_type in [VisualizationType.YOLO, VisualizationType.ALL]:
                with self.overlay_lock:
                    display_frame = self._apply_yolo_overlay(display_frame)

            # Apply optical flow overlay if requested
            if self.visualization_type in [VisualizationType.OPTICAL_FLOW, VisualizationType.ALL]:
                with self.overlay_lock:
                    display_frame = self._apply_flow_overlay(display_frame)

            # -----------------------------
            # 3. Show the frame
            # -----------------------------
            cv2.imshow('Drone Video Feed', display_frame)

            # -----------------------------
            # 4. Notify any subscribers
            # -----------------------------
            for subscriber in self.subscribers:
                try:
                    subscriber(frame.copy())
                except Exception as e:
                    print(f"Subscriber error: {str(e)}")

            # -----------------------------
            # 5. Handle keyboard input
            # -----------------------------
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

        # Cleanup
        self.stop()
