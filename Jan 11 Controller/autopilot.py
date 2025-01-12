#autopilot.py
from pymavlink import mavutil
import time
from enum import Enum
import math
import numpy as np
from threading import Thread
from video import VideoManager, VisualizationType
from optical_flow import OpticalFlowController
from controllers import AltitudeController, PositionController

# ESP32 connection settings
BROADCAST_IP = '255.255.255.255'  # Broadcast IP
ESP32_PORT = 14550  # Replace with the port your ESP32 is broadcasting on

# Local (computer) settings
LOCAL_IP = '0.0.0.0'  # Listen on all available interfaces
LOCAL_PORT = 14550  # Use the same port as the ESP32 is broadcasting on

### FLIGHT MODE LIBRARY ###
class FlightMode(Enum):
    STABILIZE = 0
    ALTHOLD = 2
    LOITER = 5
    RTL = 6
    AUTO = 3
    GUIDED = 4
    LAND = 9
    POSHOLD = 16

### DRONE COMMAND LIBRARY ###
class DroneCommands(Enum):
    ARM = "arm"
    DISARM = "disarm"
    TAKEOFF = "takeoff"
    LAND = "land"
    MOVE = "move"  # Expects additional parameters
    RTL = "return_to_launch"
    HOLD = "hold_position"

### WIFI CONTROLLER LIBRARY ###
class WiFiController:
    def __init__(self, ip="0.0.0.0", port=14550):
        """Initialize connection to drone via ESP32."""
        # For UDP connections, we need to specify 'udpin:' or 'udpout:'
        # udpin: means we're receiving on this port
        self.connection_string = f'udpin:{ip}:{port}'
        self.vehicle = None
        self.connected = False
        self.last_command_status = None
        self.command_queue = []
        self.prearm_failures = []
        self.video_manager = None
        self.optical_flow = None
        self.position_controller = None
        self.altitude_controller = None
        # MAVLink result codes for better error reporting
        self.result_codes = {
            mavutil.mavlink.MAV_RESULT_ACCEPTED: "ACCEPTED",
            mavutil.mavlink.MAV_RESULT_FAILED: "FAILED",
            mavutil.mavlink.MAV_RESULT_TEMPORARILY_REJECTED: "TEMPORARILY_REJECTED",
            mavutil.mavlink.MAV_RESULT_UNSUPPORTED: "UNSUPPORTED",
            mavutil.mavlink.MAV_RESULT_DENIED: "DENIED"
        }

### CONNECTIVITY ###
    def connect(self, timeout: float = 10.0, retry_interval: float = 0.5) -> bool:
        """
        Attempt to establish connection to the drone with timeout.
        
        Args:
            timeout (float): Maximum time to wait for connection in seconds
            retry_interval (float): Time between connection attempts in seconds
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        print(f"Attempting to connect to drone at {self.connection_string}")
        start_time = time.time()
        
        try:
            # Establish initial connection
            self.vehicle = mavutil.mavlink_connection(self.connection_string)
            
            # Wait for heartbeat with timeout
            while time.time() - start_time < timeout:
                if self.vehicle.wait_heartbeat(timeout=retry_interval):
                    self.connected = True
                    print("Connection established successfully!")
                    
                    # Request data streams
                    self.vehicle.mav.request_data_stream_send(
                        self.vehicle.target_system,
                        self.vehicle.target_component,
                        mavutil.mavlink.MAV_DATA_STREAM_ALL,
                        4,  # 4 Hz
                        1   # Start
                    )
                    return True
                
                print(f"Waiting for heartbeat... {timeout - (time.time() - start_time):.1f}s remaining")
            
            print("Connection timed out!")
            return False
            
        except Exception as e:
            print(f"Connection failed: {str(e)}")
            if self.vehicle:
                self.vehicle.close()
            self.vehicle = None
            self.connected = False
            return False

    def disconnect(self):
        """Safely disconnect from the drone."""
        # Stop all control systems
        self.stop_control_systems()

        if self.video_manager:
            try:
                self.video_manager.stop()
                print("Video manager stopped")
            except Exception as e:
                print(f"Error stopping video manager: {str(e)}")

        if self.vehicle:
            try:
                self.vehicle.close()
                print("Disconnected from drone")
            except Exception as e:
                print(f"Error during disconnection: {str(e)}")
            finally:
                self.vehicle = None
                self.connected = False

    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise ConnectionError("Failed to connect to drone")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

### PRE ARM FLIGHT CHECKS ###
    def check_prearm(self):
        """
        Perform comprehensive pre-arm checks and report status
        """
        if not self.connected or not self.vehicle:
            print("Not connected!")
            return False

        print("\n=== Pre-arm Check Results ===")
        
        # Request extended system status
        self.vehicle.mav.command_long_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
            0,
            mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
            0, 0, 0, 0, 0, 0
        )

        # Monitor messages for a brief period to collect status info
        start_time = time.time()
        status_bits = None
        voltage = None
        current = None
        battery_remaining = None
        errors_present = False

        while time.time() - start_time < 2:  # Check for 2 seconds
            msg = self.vehicle.recv_match(blocking=True, timeout=1)
            if msg is None:
                continue

            if msg.get_type() == 'SYS_STATUS':
                status_bits = msg.onboard_control_sensors_health
                voltage = msg.voltage_battery
                current = msg.current_battery
                battery_remaining = msg.battery_remaining
            
            elif msg.get_type() == 'STATUSTEXT':
                if "PreArm" in msg.text or "Arm" in msg.text:
                    print(f"Status Message: {msg.text}")
                    if "PreArm" in msg.text and ": " in msg.text:
                        self.prearm_failures.append(msg.text.split(": ")[1])
                        errors_present = True

        # Print collected information
        print("\n=== System Status ===")
        if voltage is not None:
            print(f"Battery Voltage: {voltage/1000:.2f}V")
        if current is not None:
            print(f"Battery Current: {current/100:.2f}A")
        if battery_remaining is not None:
            print(f"Battery Remaining: {battery_remaining}%")

        # Check various sensor health bits if status_bits is available
        if status_bits is not None:
            sensor_checks = [
                (mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO, "Gyroscope"),
                (mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL, "Accelerometer"),
                (mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG, "Magnetometer"),
                (mavutil.mavlink.MAV_SYS_STATUS_SENSOR_GPS, "GPS"),
                (mavutil.mavlink.MAV_SYS_STATUS_SENSOR_RC_RECEIVER, "RC Receiver")
            ]
            
            print("\n=== Sensor Status ===")
            for bit, sensor_name in sensor_checks:
                if status_bits & bit:
                    print(f"✓ {sensor_name}: OK")
                else:
                    print(f"✗ {sensor_name}: FAIL")
                    errors_present = True

        # Print any collected pre-arm failures
        if self.prearm_failures:
            print("\n=== Pre-arm Failures ===")
            for failure in self.prearm_failures:
                print(f"✗ {failure}")
            self.prearm_failures = []  # Clear for next check
        
        if not errors_present:
            print("\n✓ All checks passed - Vehicle should be armable")
        else:
            print("\n✗ Some checks failed - See above for details")

        return not errors_present

    def initialize_video(self):
        """Initialize video manager and optical flow controller"""
        if self.video_manager is None:
            self.video_manager = VideoManager(device_id=1)
            if not self.video_manager.start():
                raise RuntimeError("Failed to start video manager")
                
        if self.optical_flow is None:
            self.optical_flow = OpticalFlowController(self, self.video_manager)  # Pass self instead of self.vehicle

    def initialize_controllers(self):
        """Initialize all control systems"""
        if self.video_manager is None:
            self.video_manager = VideoManager(device_id=1)
            if not self.video_manager.start():
                raise RuntimeError("Failed to start video manager")
            
        if self.optical_flow is None:
            self.optical_flow = OpticalFlowController(self, self.video_manager)
            
        if self.altitude_controller is None:
            self.altitude_controller = AltitudeController(self.vehicle)
            
        if self.position_controller is None:
            self.position_controller = PositionController(self.vehicle)
            
        # Register observers with optical flow
        self.optical_flow.register_movement_observer(self.altitude_controller)
        self.optical_flow.register_movement_observer(self.position_controller)

    def start_control_systems(self, target_altitude=None):
        """Start all control systems"""
        print("Starting control systems...")
        self.initialize_controllers()
        self.optical_flow.start_position_hold()
        self.position_controller.start()
        self.altitude_controller.start(target_altitude)
        print("All control systems active")

    def stop_control_systems(self):
        """Stop all control systems"""
        print("Stopping control systems...")
        if self.position_controller:
            self.position_controller.stop()
        if self.altitude_controller:
            self.altitude_controller.stop()
        if self.optical_flow:
            self.optical_flow.stop()
        print("All control systems stopped")

### FLIGHT BEGINNING / END ###
    def set_flight_mode(self, mode: FlightMode, timeout: float = 5.0) -> bool:
        """
        Set the flight mode of the drone.
        
        Args:
            mode (FlightMode): Desired flight mode from FlightMode enum
            timeout (float): Time to wait for mode change confirmation
            
        Returns:
            bool: True if mode was set successfully, False otherwise
        """
        if not self.connected or not self.vehicle:
            print("Not connected to drone!")
            return False

        print(f"\nAttempting to change flight mode to {mode.name}...")
        
        # Send mode change command
        self.vehicle.mav.command_long_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,  # confirmation
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode.value,
            0, 0, 0, 0, 0  # remaining params (unused)
        )
        
        # Wait for confirmation
        start_time = time.time()
        while time.time() - start_time < timeout:
            msg = self.vehicle.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
            if msg:
                custom_mode = msg.custom_mode
                if custom_mode == mode.value:
                    print(f"✓ Flight mode changed to {mode.name}")
                    return True
        
        print(f"✗ Failed to change flight mode to {mode.name}")
        return False

    def arm(self, timeout: float = 5.0) -> bool:
        """
        Arm the drone's motors.
        
        Args:
            timeout (float): Time to wait for arm confirmation
            
        Returns:
            bool: True if armed successfully, False otherwise
        """
        if not self.connected or not self.vehicle:
            print("Not connected to drone!")
            return False
        
        print("\nInitiating arming sequence...")
        
        # First run pre-arm checks
        #if not self.check_prearm():
        #print("✗ Cannot arm: Pre-arm checks failed")
            #return False
        
        # Send arm command
        self.vehicle.mav.command_long_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,  # confirmation
            1,  # 1 to arm, 0 to disarm
            0, 0, 0, 0, 0, 0  # remaining params (unused)
        )
        
        # Wait for confirmation
        start_time = time.time()
        while time.time() - start_time < timeout:
            msg = self.vehicle.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
            if msg:
                if msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                    print("✓ Drone armed successfully")
                    return True
        
        print("✗ Arming failed")
        return False

    def disarm(self, timeout: float = 5.0) -> bool:
        """
        Disarm the drone's motors.
        
        Args:
            timeout (float): Time to wait for disarm confirmation
            
        Returns:
            bool: True if disarmed successfully, False otherwise
        """
        if not self.connected or not self.vehicle:
            print("Not connected to drone!")
            return False
        
        print("\nInitiating disarming sequence...")
        
        # Send disarm command
        self.vehicle.mav.command_long_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,  # confirmation
            0,  # 1 to arm, 0 to disarm
            0, 0, 0, 0, 0, 0  # remaining params (unused)
        )
        
        # Wait for confirmation
        start_time = time.time()
        while time.time() - start_time < timeout:
            msg = self.vehicle.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
            if msg:
                if not (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                    print("✓ Drone disarmed successfully")
                    return True
        
        print("✗ Disarming failed")
        return False

    def takeoff(self, target_altitude):
        """Enhanced takeoff with optical flow stabilization"""
        try:
            # Initialize all control systems
            print("Initializing control systems...")
            self.initialize_controllers()
            
            print("Starting takeoff sequence...")
            while self.vehicle.recv_match(blocking=False):
                pass
            
            print("Performing pre-flight checks...")
            while self.vehicle.recv_match(blocking=False):
                pass
            
            # Check if already armed
            msg = self.vehicle.recv_match(type='HEARTBEAT', blocking=True)
            if not msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                print("Sending arm command...")
                if not self.arm():
                    raise Exception("Failed to arm")
            
            # Set to ALT_HOLD mode
            print("Setting ALT_HOLD mode...")
            if not self.set_flight_mode(FlightMode.ALTHOLD):
                raise Exception("Failed to set ALT_HOLD mode")
            
            # Start optical flow in takeoff mode (lateral stability only)
            print("Starting optical flow stabilization...")
            self.optical_flow.start_takeoff_hold()

            throttle = 1600
            prev_altitude = 0
            max_vertical_speed = 0.5
            
            while True:
                msg = self.vehicle.recv_match(type='GLOBAL_POSITION_INT', blocking=True)
                current_altitude = msg.relative_alt / 1000.0
                
                vertical_speed = (current_altitude - prev_altitude) / 0.1
                prev_altitude = current_altitude
                
                print(f"Altitude: {current_altitude:.2f}m, Vertical Speed: {vertical_speed:.2f}m/s")
                
                if current_altitude >= target_altitude * 0.9:
                    progress = (current_altitude - target_altitude * 0.9) / (target_altitude * 0.1)
                    target_throttle = 1500
                    new_throttle = int(throttle - (throttle - target_throttle) * progress)
                    throttle = max(1500, new_throttle)
                else:
                    if vertical_speed < max_vertical_speed:
                        throttle = min(throttle + 2, 1620)
                    elif vertical_speed > max_vertical_speed + 0.2:
                        throttle = max(throttle - 2, 1600)
                
                # Send throttle command while optical flow handles lateral stability
                self.vehicle.mav.rc_channels_override_send(
                    self.vehicle.target_system,
                    self.vehicle.target_component,
                    0,  # Roll - handled by optical flow
                    0,  # Pitch - handled by optical flow
                    throttle,
                    0,  # Yaw - allow manual control
                    0, 0, 0, 0
                )
                
                if current_altitude >= target_altitude:
                    print("Target altitude reached!")
                    break
                    
                time.sleep(0.1)
            
            # Ensure neutral throttle
            self.vehicle.mav.rc_channels_override_send(
                self.vehicle.target_system,
                self.vehicle.target_component,
                0, 0, 1500, 0, 0, 0, 0, 0
            )
            
            # Switch to full control system
            print("Transitioning to full control system...")
            self.optical_flow.stop()  # Stop takeoff-specific optical flow
            
            # Start all control systems
            self.start_control_systems(target_altitude)

            print("Takeoff complete, maintaining position")
            return True
            
        except Exception as e:
            print(f"Takeoff failed: {str(e)}")
            self.optical_flow.stop()
            return False

    def land(self):
        """Execute a controlled landing sequence."""
        try:
            print("\nInitiating landing sequence...")
            
            # Get current altitude
            msg = self.vehicle.recv_match(type='GLOBAL_POSITION_INT', blocking=True)
            if msg:
                current_alt = msg.relative_alt / 1000.0  # Convert mm to meters
                print(f"Starting landing from {current_alt:.1f}m")
            
            # Gradually reduce altitude while maintaining position
            while current_alt > 0.3:  # Switch to final landing at 30cm
                current_alt = max(0.3, current_alt - 0.2)  # Descend 20cm at a time
                self.altitude_controller.set_target_altitude(current_alt)
                time.sleep(0.5)
            
            # Final descent
            print("Final descent...")
            self.stop_control_systems()  # Stop all controllers
            
            # Gentle descent
            self.vehicle.mav.rc_channels_override_send(
                self.vehicle.target_system,
                self.vehicle.target_component,
                0, 0, 1400, 0, 0, 0, 0, 0  # Gentle descent throttle
            )
            
            time.sleep(2.0)  # Allow time for touchdown
            
            # Stop motors
            if self.disarm():
                print("✓ Motors disarmed")
            else:
                print("✗ Failed to disarm motors")
            
            return True
            
        except Exception as e:
            print(f"Landing failed: {str(e)}")
            return False

### TELEMETRY ###
    def get_altitude(self) -> float:
        """
        Get current altitude of the drone in meters (indoor environment).
        
        Returns:
            float: Current altitude in meters, or -1 if not available
        """
        msg = self.vehicle.recv_match(type='LOCAL_POSITION_NED', blocking=True, timeout=1)
        if msg:
            return -msg.z  # Convert NED to altitude
        return -1

    def get_barometer_data(self) -> dict:
        """
        Get barometric data from the drone.
        
        Returns:
            dict: Contains 'altitude' (m), 'pressure' (hPa), and 'temperature' (C)
        """
        if not self.connected or not self.vehicle:
            return None
            
        # Request VFR_HUD message which contains altitude
        self.vehicle.mav.command_long_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
            0,
            mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
            0, 0, 0, 0, 0, 0
        )
        
        # Wait for messages
        start_time = time.time()
        while time.time() - start_time < 0.5:  # 500ms timeout
            msg = self.vehicle.recv_match(type=['VFR_HUD', 'SCALED_PRESSURE'], blocking=True, timeout=0.1)
            if msg is None:
                continue
                
            if msg.get_type() == 'VFR_HUD':
                alt = msg.alt
                break
        else:
            return None
            
        return {
            'altitude': alt,  # Altitude in meters
            'timestamp': time.time()
        }

### IN-FLIGHT COMMANDS ###
    def rotate(self, degrees: float, timeout: float = 5.0) -> bool:
        """
        Rotate the drone left (negative) or right (positive) by specified degrees.
        
        Args:
            degrees (float): Degrees to rotate (positive for right, negative for left)
            timeout (float): Maximum time to wait for rotation completion
        
        Returns:
            bool: True if rotation completed, False otherwise
        """
        if not self.connected or not self.vehicle:
            return False
            
        # Convert to radians for mavlink
        yaw_rate = 30  # degrees per second
        direction = 1 if degrees > 0 else -1
        duration = abs(degrees) / yaw_rate  # how long to rotate
        
        # Send rotation command using CONDITION_YAW
        self.vehicle.mav.command_long_send(
            self.vehicle.target_system,
            self.vehicle.target_component,
            mavutil.mavlink.MAV_CMD_CONDITION_YAW,
            0,  # confirmation
            abs(degrees),     # param1: target angle in degrees
            yaw_rate,        # param2: degrees/second rotation speed
            direction,       # param3: -1 for CCW, 1 for CW
            1,              # param4: relative offset (1) vs absolute angle (0)
            0, 0, 0         # params 5-7 (unused)
        )
        
        # Wait for rotation to complete
        time.sleep(duration)
        return True

    def move_forward_quick(self, meters: float, velocity: float = 0.5) -> bool:
        """
        Quick and dirty forward movement based purely on time estimation.
        
        Args:
            meters (float): Distance to move forward in meters
            velocity (float): Movement speed in m/s
            
        Returns:
            bool: True when movement command completed
        """
        if not self.connected or not self.vehicle:
            return False
            
        duration = meters / velocity
        
        # Send movement command
        self.vehicle.mav.set_position_target_local_ned_send(
            0, self.vehicle.target_system, self.vehicle.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            0b0000111111000111,  # mask (only use velocity components)
            0, 0, 0,            # positions (not used)
            velocity, 0, 0,     # forward, right, down velocity
            0, 0, 0,           # acceleration
            0, 0               # yaw, yaw_rate
        )
        
        # Wait estimated time
        time.sleep(duration)
        
        # Stop movement
        self.vehicle.mav.set_position_target_local_ned_send(
            0, self.vehicle.target_system, self.vehicle.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            0b0000111111000111,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        )
        return True

    def move_forward_precise(self, meters: float, velocity: float = 0.5, 
                            timeout: float = 10.0, error_threshold: float = 0.2) -> dict:
        """
        Precise forward movement using both time estimation and position feedback.
        
        Args:
            meters (float): Distance to move forward in meters
            velocity (float): Movement speed in m/s
            timeout (float): Maximum time allowed for movement
            error_threshold (float): Acceptable error margin in meters
            
        Returns:
            dict: Movement results including:
                - success: bool
                - time_estimated_distance: float
                - ned_measured_distance: float
                - error: float
                - duration: float
        """
        if not self.connected or not self.vehicle:
            return {"success": False}

        start_time = time.time()
        time_estimated_distance = 0
        
        # Get starting position
        start_pos = None
        msg = self.vehicle.recv_match(type='LOCAL_POSITION_NED', blocking=True, timeout=1)
        if msg:
            start_pos = (msg.x, msg.y)
        else:
            return {"success": False, "error": "Could not get starting position"}

        # Start movement
        self.vehicle.mav.set_position_target_local_ned_send(
            0, self.vehicle.target_system, self.vehicle.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            0b0000111111000111,
            0, 0, 0,
            velocity, 0, 0,
            0, 0, 0,
            0, 0
        )

        # Monitor both time and position
        while time.time() - start_time < timeout:
            current_time = time.time()
            elapsed_time = current_time - start_time
            time_estimated_distance = velocity * elapsed_time
            
            # Get current position
            msg = self.vehicle.recv_match(type='LOCAL_POSITION_NED', blocking=True, timeout=0.1)
            if msg:
                current_pos = (msg.x, msg.y)
                ned_measured_distance = ((current_pos[0] - start_pos[0])**2 + 
                                    (current_pos[1] - start_pos[1])**2)**0.5
                
                # Print progress every 0.5m
                if int(ned_measured_distance*2) > int((ned_measured_distance-0.1)*2):
                    print(f"Time estimated: {time_estimated_distance:.2f}m, "
                        f"NED measured: {ned_measured_distance:.2f}m")
                
                # Check if we've reached target distance
                if ned_measured_distance >= meters:
                    # Stop movement
                    self.vehicle.mav.set_position_target_local_ned_send(
                        0, self.vehicle.target_system, self.vehicle.target_component,
                        mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
                        0b0000111111000111,
                        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
                    )
                    
                    # Calculate error between methods
                    error = abs(time_estimated_distance - ned_measured_distance)
                    duration = time.time() - start_time
                    
                    result = {
                        "success": True,
                        "time_estimated_distance": time_estimated_distance,
                        "ned_measured_distance": ned_measured_distance,
                        "error": error,
                        "duration": duration
                    }
                    
                    # Warning if error is large
                    if error > error_threshold:
                        print(f"⚠️ Large positioning error detected: {error:.2f}m")
                    
                    return result

        # If we get here, we timed out
        self.vehicle.mav.set_position_target_local_ned_send(
            0, self.vehicle.target_system, self.vehicle.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            0b0000111111000111,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        )
        
        return {
            "success": False,
            "error": "Movement timed out",
            "time_estimated_distance": time_estimated_distance,
            "ned_measured_distance": "unknown",
            "duration": time.time() - start_time
        }

    def start_position_hold(self):
        """Start position holding using optical flow"""
        if not self.video_manager or not self.optical_flow:
            self.initialize_video()
        
        print("Initiating position hold...")
        self.optical_flow.start_position_hold()
        print("Position hold active")
        return True
    
    def stop_position_hold(self):
        """Stop position holding"""
        if self.optical_flow:
            self.optical_flow.stop()
            print("Position hold deactivated")
            return True
        return False
    
    def move_forward_with_position_hold(self, meters, velocity=0.5):
        """Execute forward movement while maintaining position hold"""
        if not self.position_hold_active:
            print("Warning: Position hold not active, activating now...")
            self.start_position_hold()

        # Temporarily stop position hold for movement
        self.optical_flow.stop()
        
        # Execute movement
        result = self.move_forward_precise(meters, velocity)
        
        # Resume position hold
        self.optical_flow.start_position_hold()
        
        return result
    
    def rotate_with_position_hold(self, degrees, timeout=5.0):
        """Execute rotation while maintaining position hold"""
        if not self.position_hold_active:
            print("Warning: Position hold not active, activating now...")
            self.start_position_hold()

        # Temporarily stop position hold for rotation
        self.optical_flow.stop()
        
        # Execute rotation
        result = self.rotate(degrees, timeout)
        
        # Resume position hold
        self.optical_flow.start_position_hold()
        
        return result

### MANUAL CONTROL ###
    def manual(self):
        """
        Safely transition to manual RC control by waiting for throttle stick
        to be centered before clearing overrides
        """
        print("Preparing for manual control transition...")
        print("Please center throttle stick (~1500)")
        
        while True:
            msg = self.vehicle.recv_match(type='RC_CHANNELS', blocking=True)
            rc_throttle = msg.chan3_raw
            print(f"Current RC throttle: {rc_throttle}")
            
            if abs(rc_throttle - 1500) < 50:  # Within 50 PWM of center
                print("RC throttle centered, transitioning to manual control")
                # Clear all overrides
                self.vehicle.mav.rc_channels_override_send(
                    self.vehicle.target_system,
                    self.vehicle.target_component,
                    0, 0, 0, 0, 0, 0, 0, 0
                )
                print("Manual control active")
                break
                
            time.sleep(0.1)

### EXTERNAL FILE PULLS & REFERENCES ###




### AUTOPILOT INITIALIZATION ###
def print_commands():
    """Print available commands"""
    print("\nAvailable Commands:")
    print("  check    - Run pre-arm checks")
    print("  mode     - Set flight mode")
    print("  arm      - Arm the drone")
    print("  disarm   - Disarm the drone")
    print("  takeoff  - Take off to specified altitude with position hold")
    print("  land     - Land the drone")
    print("  rotate   - Rotate drone while maintaining position")
    print("  forward  - Move forward while maintaining position")
    print("  hold     - Start position hold")
    print("  release  - Stop position hold")
    print("  status   - Print current drone status")
    print("  video    - Start video feed with optical flow visualization")
    print("  stopvideo- Stop video feed")
    print("  help     - Show this command list")
    print("  exit     - Safely land and exit")

def application():
    try:
        with WiFiController() as drone:
            print("\n=== Drone Control Interface ===")
            print("Connected to drone. Type 'help' for commands.")
            
            while True:
                try:
                    command = input("\nEnter command: ").strip().lower()
                    
                    if command == "mode":
                        print("\nAvailable Flight Modes:")
                        for mode in FlightMode:
                            print(f"  {mode.name}")
                        mode_input = input("Enter flight mode: ").strip().upper()
                        try:
                            mode = FlightMode[mode_input]
                            if drone.set_flight_mode(mode):
                                print(f"Successfully set mode to {mode.name}")
                            else:
                                print("Failed to set flight mode")
                        except KeyError:
                            print("Invalid flight mode")
                    
                    elif command == "arm":
                        if drone.arm():
                            print("Successfully armed")
                        else:
                            print("Arming failed")
                    
                    elif command == "disarm":
                        if drone.disarm():
                            print("Successfully disarmed")
                        else:
                            print("Disarming failed")
                    
                    elif command == "help":
                        print_commands()
                        
                    elif command == "check":
                        drone.check_prearm()
                        
                    elif command == "takeoff":
                        if drone.takeoff(1):
                            print("Successfully took off to 1.5m")
                        else:
                            print("Takeoff failed")
                            
                    elif command == "land":
                        if drone.land():
                            print("Successfully landed")
                        else:
                            print("Landing failed")

                    elif command == "video":
                        print("\nStarting video feed with optical flow visualization...")
                        try:
                            # Clean up any existing video manager
                            if drone.video_manager is not None:
                                drone.video_manager.stop()
                                drone.video_manager = None
                            
                            # Initialize new video manager
                            drone.video_manager = VideoManager(device_id=1)
                            
                            # Start optical flow first
                            drone.initialize_controllers()
                            drone.optical_flow.start_position_hold()
                            
                            # Start video (this will block until 'q' is pressed)
                            drone.video_manager.start()
                            
                        except Exception as e:
                            print(f"Failed to start video feed: {e}")

                    elif command == "stopvideo":
                        print("\nStopping video feed...")
                        try:
                            if drone.optical_flow:
                                drone.optical_flow.stop()
                            if drone.video_manager:
                                drone.video_manager.stop()
                            print("Video feed stopped")
                        except Exception as e:
                            print(f"Error stopping video feed: {str(e)}")
                            
                    #elif command.startswith("rotate"):
                        #try:
                            #degrees = float(input("Enter degrees (positive=right, negative=left): "))
                            #if drone.rotate(degrees):
                                #print(f"Rotated {degrees} degrees")
                            #else:
                                #print("Rotation failed")
                        #except ValueError:
                            #print("Please enter a valid number")
                            
                    #elif command.startswith("forward"):
                        #try:
                            #meters = float(input("Enter distance in meters: "))
                            #if drone.move_forward_quick(meters):
                                #print(f"Moved forward {meters}m")
                            #else:
                                #print("Movement failed")
                        #except ValueError:
                            #print("Please enter a valid number")
                            
                    elif command == "status":
                        altitude = drone.get_altitude()
                        print(f"\nCurrent Status:")
                        print(f"Altitude: {altitude:.2f}m")
                        print(f"Motors Armed: {drone.vehicle.motors_armed()}")
                        msg = drone.vehicle.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
                        if msg:
                            current_mode = next((mode for mode in FlightMode if mode.value == msg.custom_mode), None)
                            print(f"Flight Mode: {current_mode.name if current_mode else 'Unknown'}")
                            
                    elif command == "exit":
                        print("\nInitiating safe shutdown...")
                        if drone.vehicle.motors_armed():
                            print("Landing before exit...")
                            drone.land()
                        print("Exiting program")
                        break

                    elif command == "hold":
                        if drone.start_position_hold():
                            print("Position hold activated")
                        else:
                            print("Failed to activate position hold")

                    elif command == "release":
                        if drone.stop_position_hold():
                            print("Position hold deactivated")
                        else:
                            print("Failed to deactivate position hold")

                    elif command.startswith("forward"):
                        try:
                            meters = float(input("Enter distance in meters: "))
                            result = drone.move_forward_with_position_hold(meters)
                            if result["success"]:
                                print(f"Moved forward {meters}m while maintaining position")
                                print(f"Measured distance: {result['ned_measured_distance']:.2f}m")
                            else:
                                print(f"Movement failed: {result['error']}")
                        except ValueError:
                            print("Please enter a valid number")

                    elif command.startswith("rotate"):
                        try:
                            degrees = float(input("Enter degrees (positive=right, negative=left): "))
                            if drone.rotate_with_position_hold(degrees):
                                print(f"Rotated {degrees} degrees while maintaining position")
                            else:
                                print("Rotation failed")
                        except ValueError:
                            print("Please enter a valid number")
                        
                    else:
                        print("Unknown command. Type 'help' for available commands.")
                        
                except KeyboardInterrupt:
                    print("\n\nUser interrupted command!")
                    continue
                    
    except KeyboardInterrupt:
        print("\n\nEmergency stop triggered!")
        print("Initiating emergency landing...")
        try:
            if 'drone' in locals():
                drone.land()
        except:
            print("Emergency landing failed!")
    except Exception as e:
        print(f"\n\nUnexpected error: {str(e)}")
        print("Initiating emergency landing...")
        try:
            if 'drone' in locals():
                drone.land()
        except:
            print("Emergency landing failed!")

if __name__ == "__main__":
    application()