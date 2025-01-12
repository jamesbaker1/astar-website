#optical_flow.py
import cv2
import numpy as np
import time
from video import VideoManager, VisualizationType

class OpticalFlowController:
    def __init__(self, controller, video_manager):
        self.controller = controller
        self.vehicle = controller.vehicle
        self.video_manager = video_manager
        self.prev_frame = None
        self.running = False
        self.is_takeoff = False
        
        # Movement observers
        self.movement_observers = []
        
        # Control parameters
        self.dead_zone = 5.0  # Pixels of movement to ignore
        self.z_dead_zone = 0.02  # Scale change threshold
        self.kp_z = 0.15  # Proportional gain for forward/backward movement
        
        # Feature detection parameters
        self.feature_params = dict(
            maxCorners=100,
            qualityLevel=0.3,
            minDistance=7,
            blockSize=7
        )
        
        self.lk_params = dict(
            winSize=(15, 15),
            maxLevel=2,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
        )

    def register_movement_observer(self, observer):
        """Register an observer to receive movement updates"""
        self.movement_observers.append(observer)

    def remove_movement_observer(self, observer):
        """Remove an observer"""
        if observer in self.movement_observers:
            self.movement_observers.remove(observer)

    def calculate_flow(self, current_frame):
        """Calculate optical flow for all dimensions"""
        current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
        
        if self.prev_frame is None:
            self.prev_frame = current_gray
            return 0, 0, 0, []
            
        # Find features in previous frame
        p0 = cv2.goodFeaturesToTrack(self.prev_frame, mask=None, **self.feature_params)
        if p0 is None:
            return 0, 0, 0, []
        
        # Calculate optical flow
        p1, status, err = cv2.calcOpticalFlowPyrLK(
            self.prev_frame, current_gray, p0, None, **self.lk_params
        )
        
        # Select good points
        good_new = p1[status == 1]
        good_old = p0[status == 1]
        
        if len(good_new) > 0 and len(good_old) > 0:
            # Calculate movements with outlier rejection
            movements = self._calculate_movements_with_outliers(good_old, good_new, current_gray.shape)
            self.prev_frame = current_gray
            return movements
        
        self.prev_frame = current_gray
        return 0, 0, 0, []

    def _calculate_movements_with_outliers(self, good_old, good_new, frame_shape):
        """Calculate movements in all dimensions with statistical outlier rejection"""
        height, width = frame_shape
        center_x, center_y = width / 2, height / 2
        
        x_movements = []
        y_movements = []
        scale_changes = []
        flow_vectors = []
        
        for old_point, new_point in zip(good_old, good_new):
            old_x, old_y = old_point.ravel()
            new_x, new_y = new_point.ravel()
            
            # Calculate lateral movement
            x_movements.append(new_x - old_x)
            y_movements.append(new_y - old_y)
            
            # Calculate scale change for altitude estimation
            old_dist = np.sqrt((old_x - center_x)**2 + (old_y - center_y)**2)
            new_dist = np.sqrt((new_x - center_x)**2 + (new_y - center_y)**2)
            
            if old_dist > 0:
                scale_change = (new_dist - old_dist) / old_dist
                scale_changes.append(scale_change)
            
            flow_vectors.append((old_point.reshape(-1), (new_point - old_point).reshape(-1)))
        
        # Reject outliers
        x_movement = self._reject_outliers(x_movements)
        y_movement = self._reject_outliers(y_movements)
        scale_change = self._reject_outliers(scale_changes) if scale_changes else 0
        
        return x_movement, y_movement, scale_change, flow_vectors

    def _reject_outliers(self, data):
        """Reject outliers using IQR method"""
        if not data:
            return 0
            
        q1 = np.percentile(data, 25)
        q3 = np.percentile(data, 75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        filtered_data = [x for x in data if lower_bound <= x <= upper_bound]
        return np.mean(filtered_data) if filtered_data else 0

    def process_frame(self, frame):
        """Process a new frame and notify all observers"""
        if not self.running:
            return
            
        try:
            # Calculate optical flow for all dimensions
            x_movement, y_movement, scale_change, flow_vectors = self.calculate_flow(frame)
            
            # Update visualization
            self.video_manager.update_flow_overlay(flow_vectors, scale_change)

            # Get barometer data from the controller
            baro_data = None  # Initialize as None
            try:
                baro_data = self.controller.get_barometer_data()
            except:
                pass  # Ignore barometer errors for now to keep video running

            # Notify observers
            movement_data = {
                'x': x_movement,
                'y': y_movement,
                'scale': scale_change,
                'timestamp': time.time(),
                'is_takeoff': self.is_takeoff,
                'flow_vectors': flow_vectors,
                'baro_data': baro_data
            }
            
            for observer in self.movement_observers:
                observer.on_movement(movement_data)
            
        except Exception as e:
            print(f"Error processing frame: {e}")

    def start_position_hold(self):
        """Start position holding"""
        if not self.running:
            self.running = True
            self.is_takeoff = False
            self.prev_frame = None
            self.integral_x = 0
            self.integral_y = 0
            self.video_manager.subscribe(self.process_frame)
            self.video_manager.set_visualization(VisualizationType.OPTICAL_FLOW)
            print("Started position hold mode")

    def start_takeoff_hold(self):
        """Start position holding during takeoff (x,y only)"""
        if not self.running:
            self.running = True
            self.is_takeoff = True
            self.prev_frame = None
            self.integral_x = 0
            self.integral_y = 0
            self.video_manager.subscribe(self.process_frame)
            self.video_manager.set_visualization(VisualizationType.OPTICAL_FLOW)
            print("Started takeoff hold mode")

    def stop(self):
        """Stop position holding"""
        self.running = False
        # Clear any cached frames
        self.prev_frame = None
        # Clear movement data
        self.integral_x = 0
        self.integral_y = 0
        self.video_manager.unsubscribe(self.process_frame)
        print("Stopped optical flow controller")