# ideo.py
import cv2
import numpy as np
from threading import Thread, Lock
from queue import Queue
import time

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
        self.overlay_lock = Lock()
        self.flow_overlay = None
        self.debug = True  # Add this line to fix the attribute error

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
            self._run_display_loop()  # Run in main thread like your working code
            return True
            
        except Exception as e:
            print(f"Error starting video manager: {str(e)}")
            self.stop()
            return False

    def stop(self):
        """Stop video capture"""
        self.running = False
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

    def _capture_loop(self):
        """Main capture loop"""
        frame_count = 0
        last_fps_time = time.time()
        
        print("Capture loop starting...")
        
        while self.running:
            try:
                if not self.camera.isOpened():
                    print("Camera is not opened")
                    time.sleep(0.5)
                    continue
                
                ret, frame = self.camera.read()
                if not ret or frame is None:
                    print("Failed to capture frame")
                    time.sleep(0.1)
                    continue
                
                # Update frame count and FPS
                frame_count += 1
                if frame_count % 30 == 0:
                    current_time = time.time()
                    fps = 30 / (current_time - last_fps_time)
                    print(f"Camera FPS: {fps:.1f}")
                    last_fps_time = current_time
                
                # Update latest frame
                with self.frame_lock:
                    self.latest_frame = frame.copy()
                
                # Add to buffer (non-blocking)
                if not self.frame_buffer.full():
                    self.frame_buffer.put(frame)
                
                # Notify subscribers
                frame_copy = frame.copy()
                for subscriber in self.subscribers:
                    try:
                        subscriber(frame_copy)
                    except Exception as e:
                        print(f"Subscriber error: {str(e)}")
                
            except Exception as e:
                print(f"Capture error: {str(e)}")
                time.sleep(0.1)
        
        print("Capture loop ending...")

    def _display_loop(self):
        """Main display loop"""
        print("Display loop starting...")
        window_name = 'Drone Video Feed'
        
        # Initial window creation
        try:
            cv2.namedWindow(window_name)
            print("Window created successfully")
        except Exception as e:
            print(f"Window creation failed: {e}")
            return
            
        frame_count = 0
        last_time = time.time()
        
        while self.running and self.display_active:
            try:
                ret, frame = self.camera.read()
                if not ret:
                    print("Failed to read frame")
                    continue
                
                frame_count += 1
                if frame_count % 30 == 0:
                    current_time = time.time()
                    fps = 30 / (current_time - last_time)
                    print(f"FPS: {fps:.1f}")
                    last_time = current_time
                
                # Apply visualizations if needed
                display_frame = frame.copy()
                with self.overlay_lock:
                    if self.visualization_type in [VisualizationType.OPTICAL_FLOW, VisualizationType.ALL]:
                        if self.flow_overlay:
                            display_frame = self._apply_flow_overlay(display_frame)
                
                # Display the frame
                cv2.imshow(window_name, display_frame)
                
                # Notify subscribers
                for subscriber in self.subscribers:
                    try:
                        subscriber(frame.copy())
                    except Exception as e:
                        print(f"Subscriber error: {str(e)}")
                
                # Handle keyboard input with shorter wait time
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    self.display_active = False
                    break
                    
            except Exception as e:
                print(f"Display loop error: {str(e)}")
                time.sleep(0.1)
        
        # Cleanup
        try:
            cv2.destroyWindow(window_name)
            cv2.waitKey(1)  # Additional wait for macOS
        except:
            pass

    def _run_display_loop(self):
        """Simple display loop similar to your working code"""
        print("Starting display loop")
        
        while self.running:
            ret, frame = self.camera.read()
            if not ret:
                continue
            
            # Create copy for display
            display_frame = frame.copy()
            
            # Apply optical flow visualization if active
            if self.visualization_type in [VisualizationType.OPTICAL_FLOW, VisualizationType.ALL]:
                if self.flow_overlay:
                    flow_vectors, z_movement = self.flow_overlay
                    # Draw flow vectors
                    for vector in flow_vectors:
                        x, y = vector[0]
                        dx, dy = vector[1]
                        cv2.arrowedLine(display_frame, 
                                      (int(x), int(y)), 
                                      (int(x + dx), int(y + dy)),
                                      (0, 255, 0), 2)
            
            # Display frame
            cv2.imshow('Drone Video Feed', display_frame)
            
            # Notify subscribers (optical flow calculation)
            for subscriber in self.subscribers:
                try:
                    subscriber(frame.copy())
                except Exception as e:
                    print(f"Subscriber error: {str(e)}")
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

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