#controllers.py
import numpy as np
import time
from threading import Thread

class AltitudeController:
    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.running = False
        self.control_thread = None
        self.target_altitude = 0
        self.last_optical_update = 0
        self.last_baro_update = 0
        
        # Control parameters
        self.base_throttle = 1500
        self.kp_alt = 15  # Proportional gain
        self.ki_alt = 0.1  # Integral gain
        self.kp_optical = 10  # Gain for optical flow input
        self.max_correction = 100
        self.correction_threshold = 0.05  # Threshold to determine when to break out of deadzone
        
        # Data smoothing
        self.smoothed_scale = 0
        self.alpha_scale = 0.2  # Exponential smoothing factor

        # Error tracking
        self.integral_error = 0
        self.prev_error = 0
        self.last_baro_altitude = None

        # Periodic barometer check interval
        self.baro_check_interval = 0.1  # seconds
        
    def on_movement(self, movement_data):
        """Receive movement updates from optical flow"""
        if not self.running or movement_data['is_takeoff']:
            return
        
        current_time = movement_data['timestamp']

        # Get barometer reading periodically
        baro_data = movement_data.get('baro_data')
        if baro_data:
            self.update_from_barometer(baro_data)
            self.last_baro_update = current_time
        
        # Update based on optical flow scale changes
        scale_change = movement_data['scale']

        # Apply exponential smoothing to scale change
        self.smoothed_scale = (self.alpha_scale * scale_change + 
                              (1 - self.alpha_scale) * self.smoothed_scale)
        
        # Calculate correction
        optical_correction = -scale_change * self.kp_optical
        
        # Combine barometer and optical flow corrections
        if self.last_baro_altitude is not None:
            baro_error = self.target_altitude - self.last_baro_altitude
            self.integral_error += baro_error * (current_time - self.last_baro_update)
            baro_correction = (baro_error * self.kp_alt + 
                             self.integral_error * self.ki_alt)
            
            # Weighted combination of corrections
            total_correction = (0.7 * baro_correction + 
                              0.3 * optical_correction)
        else:
            total_correction = optical_correction
        
        # Apply correction with deadzone logic
        if abs(total_correction) > self.correction_threshold:
            if total_correction > 0:
                throttle = min(1620, self.base_throttle + 
                             abs(total_correction))  # Climb
            else:
                throttle = max(1380, self.base_throttle - 
                             abs(total_correction))  # Descend
        else:
            throttle = self.base_throttle  # Stay in deadzone
        
        self.last_optical_update = movement_data['timestamp']
        
        # Send the RC command
        self.vehicle.mav.rc_channels_override_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            0,        # Don't touch roll
            0,        # Don't touch pitch
            throttle, # Altitude adjustment
            0,        # Don't touch yaw
            0, 0, 0, 0
        )
    
    def update_from_barometer(self, baro_data):
        """Process new barometer data"""
        self.last_baro_altitude = baro_data['altitude']

    def start(self, target_altitude=None):
        """Start altitude maintenance"""
        if target_altitude is not None:
            self.target_altitude = target_altitude
        self.running = True
        self.smoothed_scale = 0
        self.integral_error = 0
        self.last_baro_altitude = None
        print("Altitude controller started")

    def stop(self):
        """Stop altitude maintenance"""
        self.running = False
        print("Altitude controller stopped")

    def set_target_altitude(self, altitude):
        """Change target altitude"""
        self.target_altitude = altitude
        self.integral_error = 0  # Reset integral term


class PositionController:
    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.running = False
        
        # Control parameters
        self.kp_xy = 0.3
        self.max_correction = 100
        
    def on_movement(self, movement_data):
        """Receive movement updates from optical flow"""
        if not self.running:
            return
            
        # Calculate position corrections
        x_correction = int(-movement_data['x'] * self.kp_xy)
        y_correction = int(-movement_data['y'] * self.kp_xy)
        
        # Apply corrections
        roll = 1500 + np.clip(x_correction, -self.max_correction, self.max_correction)
        pitch = 1500 + np.clip(y_correction, -self.max_correction, self.max_correction)
        
        # Send RC commands for position control
        self.vehicle.mav.rc_channels_override_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            roll,
            pitch,
            0,  # Throttle handled by altitude controller
            0,  # Yaw
            0, 0, 0, 0
        )
        
    def start(self):
        """Start position control"""
        self.running = True
        print("Position controller started")
        
    def stop(self):
        """Stop position control"""
        self.running = False
        print("Position controller stopped")