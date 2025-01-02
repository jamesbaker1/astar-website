import * as THREE from 'https://threejsfundamentals.org/threejs/resources/threejs/r127/build/three.module.js';
import {GLTFLoader} from 'https://threejsfundamentals.org/threejs/resources/threejs/r127/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'https://threejsfundamentals.org/threejs/resources/threejs/r127/examples/jsm/loaders/DRACOLoader.js';
import {OrbitControls} from 'https://threejsfundamentals.org/threejs/resources/threejs/r127/examples/jsm/controls/OrbitControls.js';
import { RGBELoader } from 'https://threejsfundamentals.org/threejs/resources/threejs/r127/examples/jsm/loaders/RGBELoader.js';
import { Sky } from 'https://threejsfundamentals.org/threejs/resources/threejs/r127/examples/jsm/objects/Sky.js';

// ---------------------------------------------------------------------------
// GLOBALS
// ---------------------------------------------------------------------------

// Drone and environment setup
var drone;
var bomb;
var mixer;
var mixerbomb;
var scene = new THREE.Scene();

// Propellers array to store references to propeller meshes
var propellers = [];

// We'll store environment bounding boxes here
var environmentBoxes = [];
var environmentHelpers = []; // Store helpers for environment boxes

// Drone bounding box
var droneBox = new THREE.Box3();
var droneHelper; // We'll create this after drone loads

// Variable to store the last safe position of the drone
var lastSafePosition = new THREE.Vector3();

// Setup Sky
const sky = new Sky();
sky.scale.setScalar(10000);
// scene.add(sky);

const skyUniforms = sky.material.uniforms;
skyUniforms['turbidity'].value = 5;
skyUniforms['rayleigh'].value = 2;
skyUniforms['mieCoefficient'].value = 0.005;
skyUniforms['mieDirectionalG'].value = 0.5;

const sun = new THREE.Vector3();
function updateSunPosition() {
    const theta = Math.PI * (0.45 - 0.5);
    const phi = 2 * Math.PI * (0.25 - 0.5);
    sun.x = Math.cos(phi);
    sun.y = Math.sin(phi) * Math.sin(theta);
    sun.z = Math.sin(phi) * Math.cos(theta);
    sky.material.uniforms['sunPosition'].value.copy(sun);
}
updateSunPosition();

var camera = new THREE.PerspectiveCamera(
    75, window.innerWidth / window.innerHeight, 0.1, 1000
);
var renderer = new THREE.WebGLRenderer();
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

// For HDR env maps, not strictly needed here
const rgbeLoader = new RGBELoader();

// GLTF + DRACO loader
var loader = new GLTFLoader();
loader.setDRACOLoader(new DRACOLoader().setDecoderPath('https://www.gstatic.com/draco/v1/decoders/'));

// Load Drone
const droneURL = (window.location.hostname === 'localhost')
  ? '/models/Drone.glb' 
  : 'https://itxebbadjnoj2hjf.public.blob.vercel-storage.com/Drone-MIyyPRsUFRxuWH7H9ErHhk9dJK2GHP.glb';

loader.load(
    droneURL,
    function(gltf) {
      drone = gltf.scene;
      drone.position.set(-62.26, 30.40, 124.26); 
      drone.scale.set(5,5,5);
      drone.traverse(function(child) {
        if (child.isMesh) {
          child.castShadow = true;
          child.receiveShadow = true;
        }
        if (child.name && child.name.toLowerCase().includes('propeller')) {
          propellers.push(child);
        }
      });
      scene.add(drone);

      mixer = new THREE.AnimationMixer(drone);
      gltf.animations.forEach((clip) => {
        mixer.clipAction(clip).play();
      });

      // Drone bounding box helper
      drone.updateMatrixWorld(true);
      droneBox.setFromObject(drone);

      lastSafePosition.copy(drone.position);

      // Position camera behind drone initially
      // camera.position.set(drone.position.x, drone.position.y, drone.position.z + 5);
      // camera.postition.set(-31.96, 10.88, -51.47);
      camera.lookAt(drone.position);
    },
    undefined,
    function(error) {
      console.error(error);
    }
);

// Environment ground texture (optional)
var texture = new THREE.TextureLoader().load('/models/ground.jpg');
texture.wrapS = THREE.RepeatWrapping;
texture.wrapT = THREE.RepeatWrapping;
texture.castShadow = false;
texture.repeat.set(5, 5);

// Load city or environment
var mount;
const sceneURL = (window.location.hostname === 'localhost')
  ? '/models/cs_office_csgo_real_light_version.glb' 
  : 'https://itxebbadjnoj2hjf.public.blob.vercel-storage.com/cs_office_csgo_real_light_version-DFy0wCAXhqayBQP2zIfm3SGjG5vJNv.glb';
// const sceneURL = '/models/st_lukes_court_harrogate_city_block.glb'

loader.load(
  sceneURL, 
  function(gltf) {
    mount = gltf.scene;
    mount.position.set(50,50,50);
    mount.scale.set(.1,.1,.1);
    scene.add(mount);
    mount.updateMatrixWorld(true);
    mount.traverse((child) => {
        if (child.isMesh) {
        //   child.material = new THREE.MeshLambertMaterial({ color: 0x666666 });
            child.material.color.multiplyScalar(3.5);
        }
      });
  },
  undefined,
  function(error) {
    console.error(error);
  }
);
// scene.traverse((child) => {
//     if (child.isMesh) {
//       child.material = new THREE.MeshLambertMaterial({ color: 0xffffff });
//     }
// });

var light = new THREE.AmbientLight(0x888888, 1);
light.intensity = 5;
var pointLight = new THREE.PointLight(0xffffff, 0.5, 100);
pointLight.position.set(10, 20, 10);
scene.add(light, pointLight);
const ambientLight = new THREE.HemisphereLight(0xffffff, 2); // color, intensity
scene.add(ambientLight);
var strongHemisphere = new THREE.HemisphereLight(0xffffff, 0x080820, 5);
scene.add(strongHemisphere);

// scene.background = new THREE.Color(0xffffff);
// scene.fog = new THREE.Fog(0xCCBDC5, 30, 120);

// Initial camera + OrbitControls
// camera.position.set(-31.96, 10.88, -51.47);
var controls = new OrbitControls(camera, renderer.domElement);
controls.minDistance = 20;
controls.maxDistance = 20;
controls.update();
camera.position.set(-81.33, 35.34, 122.74);

// Bomb placeholders
var bombDropped = false;
var bombAnimation = false;

// Physics and control variables
var clock = new THREE.Clock();
var velocity = new THREE.Vector3(0,0,0);
var acceleration = new THREE.Vector3(0,0,0);

const gravity = -0.005;
const liftPower = 0.01;
// Instead of "var desiredAltitude = 1;", use window to make it globally modifiable
window.desiredAltitude = 30;

var pitch = 0;
var roll = 0;
var yaw = 1.51;
var yawOffset = 0;

// For UI updates
var speed = 0;
var lastPosition = new THREE.Vector3();

// Drone cameras
var droneCamera = new THREE.PerspectiveCamera(90, window.innerWidth / window.innerHeight, 0.1, 1000);
droneCamera.position.set(0, 2, -5);
var droneCameraTwo = droneCamera.clone();

var droneView = false;  
var bottomView = false;  
var fix_camera = true;

// Keyboard
var keysPressed = {};

// ---------------------------------------------------------------------------
// RE-ENABLE W & S for forward/backward
// ---------------------------------------------------------------------------
const keyMap = {
  'w': { type: 'forward',  value: -0.05 },
  's': { type: 'forward',  value:  0.05 },
  'a': { type: 'yaw',      value:  0.05 },
  'd': { type: 'yaw',      value: -0.05 },
  'i': { type: 'altitude', value:  5 },
  'k': { type: 'altitude', value: -5 },
  'j': { type: 'roll',     value: -0.1 },
  'l': { type: 'roll',     value:  0.1 }
};

var flipPitch = 0;
var flipRoll = 0;

window.addEventListener('keydown', function(event) {
  const key = event.key.toLowerCase();
  if (keyMap[key]) {
    keysPressed[key] = true;
  }

  if (key === 'c') {
    droneView = !droneView; 
    bottomView = false;
  }
  if (key === 'm') {
    bottomView = !bottomView; 
    droneView = false;
  }
  if (key === 'b') {
    bombDropped = true;
    bombAnimation = true;
  }

  // Flips
  // switch(event.key) {
  //   case 'ArrowUp':
  //     flipPitch = Math.PI; break;
  //   case 'ArrowDown':
  //     flipPitch = -Math.PI; break;
  //   case 'ArrowLeft':
  //     flipRoll = Math.PI; break;
  //   case 'ArrowRight':
  //     flipRoll = -Math.PI; break;
  // }
});

window.addEventListener('keyup', function(event) {
  const key = event.key.toLowerCase();
  if (keysPressed[key]) {
    delete keysPressed[key];
  }

  // Reset flips
  if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    flipPitch = 0;
  }
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    flipRoll = 0;
  }
});

function applyControls() {
  let altitudeInput = 0;
  let forwardInput  = 0;
  yawOffset = 0;
  roll = 0;

  for (let k in keysPressed) {
    const mapping = keyMap[k];
    if (!mapping) continue;

    switch(mapping.type) {
      case 'forward':
        forwardInput += mapping.value;
        break;
      case 'yaw':      
        yawOffset += mapping.value;   
        break;
      case 'roll':     
        roll += mapping.value;        
        break;
      case 'altitude': 
        altitudeInput += mapping.value; 
        break;
    }
  }

  yaw += yawOffset;
  // Update the global desiredAltitude
  window.desiredAltitude += altitudeInput * 0.05;
  if (window.desiredAltitude < 0) window.desiredAltitude = 0;

  // Combine forwardInput with flips for final pitch
  pitch = forwardInput + flipPitch;
  roll  += flipRoll;
}

// ---------------------------------------------------------------------------
// STEER DRONE TOWARD BBOX (AI logic): Turn first, then move forward
// ---------------------------------------------------------------------------
function steerDroneTowardBBox(deltaTime) {
  // 1) If we still have yaw to complete
  if (Math.abs(window.yawNeeded) > 0.0001) {
    console.log(yawNeeded);
    const turnStep = 0.05; // how fast we turn per frame
    if (window.yawNeeded > 0) {
      const amt = Math.min(turnStep, window.yawNeeded);
      yaw += amt;
      window.yawNeeded -= amt;
    } else {
      const amt = Math.min(turnStep, Math.abs(window.yawNeeded));
      yaw -= amt;
      window.yawNeeded += amt;
    }
  } 
  // 2) If we've finished turning, move forward some distance
  else if (window.distanceToTravel > 0) {
    console.log("trying to go forward")
    const moveStep = 0.1;  // meters per frame
    window.distanceToTravel -= moveStep;
    if (window.distanceToTravel <= 0) {
      pitch = 0;
      console.log("AI pilot: completed forward motion");
    } else {
      pitch = -0.02; // AI-driven forward tilt
    }
  }
}

// Depth material for mini-map
const depthMaterial = new THREE.MeshDepthMaterial();
depthMaterial.depthPacking = THREE.RGBADepthPacking;
depthMaterial.blending = THREE.NoBlending;

// Offscreen target for reading droneCam
let droneRenderTarget = new THREE.WebGLRenderTarget(320, 240);

function updateInfo() {
  var speedElement = document.getElementById('speed');
  var positionElement = document.getElementById('position');
  var cameraPositionElement = document.getElementById('camera-position');

  // Info for yaw/pitch/roll
  var pitchElement = document.getElementById('pitch-info');
  var yawElement   = document.getElementById('yaw-info');
  var rollElement  = document.getElementById('roll-info');

  if (!drone) return;

  // Calculate drone speed
  var distance = drone.position.distanceTo(lastPosition);
  speed = distance / (1/60);
  lastPosition.copy(drone.position);

  // Update speed, position, camera position
  if (speedElement) {
    speedElement.innerText = 'Speed: ' + speed.toFixed(2);
  }
  if (positionElement) {
    positionElement.innerText =
      'Position: (' + drone.position.x.toFixed(2) + ', ' +
      drone.position.y.toFixed(2) + ', ' +
      drone.position.z.toFixed(2) + ')';
  }
  if (cameraPositionElement) {
    cameraPositionElement.innerText =
      'Camera Position: (' + camera.position.x.toFixed(2) + ', ' +
      camera.position.y.toFixed(2) + ', ' +
      camera.position.z.toFixed(2) + ')';
  }

  // Update yaw, pitch, roll
  if (pitchElement) pitchElement.innerText = 'Pitch: ' + pitch.toFixed(2);
  if (yawElement)   yawElement.innerText   = 'Yaw: ' + yaw.toFixed(2);
  if (rollElement)  rollElement.innerText  = 'Roll: ' + roll.toFixed(2);
}

function animate() {
  requestAnimationFrame(animate);

  if (!drone) {
    renderer.render(scene, camera);
    return;
  }

  var deltaTime = clock.getDelta();

  // 1. Apply normal keyboard controls
  applyControls();

  // 2. AI autopilot logic (yaw, then forward)
  steerDroneTowardBBox(deltaTime);

  // Build final orientation
  var euler = new THREE.Euler(pitch, yaw, roll, 'YXZ');
  var quaternion = new THREE.Quaternion().setFromEuler(euler);
  drone.quaternion.copy(quaternion);

  // Basic vertical physics
  acceleration.set(0, gravity, 0);
  let currentAltitude = drone.position.y;
  // Use the global desiredAltitude
  let altitudeError = window.desiredAltitude - currentAltitude;
  acceleration.y += altitudeError * liftPower;

  // Forward/backward, left/right from pitch/roll
  var forward = new THREE.Vector3(0,0,-1).applyQuaternion(quaternion);
  var right   = new THREE.Vector3(-1,0,0).applyQuaternion(quaternion);
  acceleration.addScaledVector(forward, pitch * 0.5);
  acceleration.addScaledVector(right,  roll  * 0.25);

  velocity.addScaledVector(acceleration, deltaTime * 60);
  // Damping
  velocity.multiplyScalar(0.9);

  // Move the drone
  drone.position.addScaledVector(velocity, deltaTime * 60);

//   if (drone.position.y < 0) {
//     drone.position.y = 0;
//     velocity.y = 0;
//   }

  // Update bounding box
  drone.updateMatrixWorld(true);
  droneBox.setFromObject(drone);

  // Collision detection
  let isColliding = false;
//   for (let i = 0; i < environmentBoxes.length; i++) {
//     if (droneBox.intersectsBox(environmentBoxes[i])) {
//       isColliding = true;
//       break;
//     }
//   }
  // Collision response
//   if (isColliding) {
//     drone.position.copy(lastSafePosition);
//     velocity.set(0,0,0);
//   } else {
//     lastSafePosition.copy(drone.position);
//   }

  // Update Drone Cameras
  droneCamera.position.copy(drone.position);
  droneCamera.position.add(new THREE.Vector3(0,0.5,1).applyQuaternion(drone.quaternion));
  droneCamera.quaternion.copy(drone.quaternion);
  let backwardRotation = new THREE.Quaternion();
  backwardRotation.setFromAxisAngle(new THREE.Vector3(0,1,0), Math.PI);
  droneCamera.quaternion.multiply(backwardRotation);

  droneCameraTwo.position.copy(drone.position);
  droneCameraTwo.position.add(new THREE.Vector3(0,-0.2,0.2).applyQuaternion(drone.quaternion));
  droneCameraTwo.quaternion.copy(drone.quaternion);
  droneCameraTwo.quaternion.multiply(backwardRotation);

  // OrbitControls follow the drone
  controls.target.copy(drone.position);
  controls.update();

  // Decide which camera to render
  var activeCamera;
  if (droneView) {
    activeCamera = droneCamera;
  } else if (bottomView) {
    activeCamera = droneCameraTwo;
  } else {
    activeCamera = camera;
  }

  // Update mixer (animations), rotate propellers
  if (mixer) mixer.update(deltaTime);
  propellers.forEach((propeller) => {
    propeller.rotation.y += 20 * deltaTime;
  });

  // Main render
  renderer.setScissorTest(false);
  renderer.setViewport(0, 0, window.innerWidth, window.innerHeight);
  renderer.render(scene, activeCamera);

  // Small FPV + Depth map in corners
  const insetWidth = 320;
  const insetHeight = 240;
  const padding = 10;
  const fullWidth = renderer.domElement.clientWidth;
  const fullHeight = renderer.domElement.clientHeight;

  // FPV view in corner
  const fpvCam = droneCamera;
  renderer.setScissorTest(true);
  renderer.setViewport(padding, fullHeight - insetHeight - padding, insetWidth, insetHeight);
  renderer.setScissor(padding, fullHeight - insetHeight - padding, insetWidth, insetHeight);
  renderer.render(scene, fpvCam);

  // Depth map next to FPV
  scene.overrideMaterial = depthMaterial;
  renderer.setViewport(padding + insetWidth + padding, fullHeight - insetHeight - padding, insetWidth, insetHeight);
  renderer.setScissor(padding + insetWidth + padding, fullHeight - insetHeight - padding, insetWidth, insetHeight);
  renderer.render(scene, fpvCam);
  scene.overrideMaterial = null;
  renderer.setScissorTest(false);

  // --- OFF-SCREEN RENDER PASS (droneCam image capture) ---
  const originalRenderTarget = renderer.getRenderTarget();
  renderer.setRenderTarget(droneRenderTarget);
  renderer.clear();
  renderer.render(scene, droneCamera);

  const width = droneRenderTarget.width;
  const height = droneRenderTarget.height;
  const buffer = new Uint8Array(width * height * 4);
  renderer.readRenderTargetPixels(droneRenderTarget, 0, 0, width, height, buffer);

  // Flip the rows in "buffer"
  const flippedBuffer = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    const srcY = (height - 1 - y);
    const srcOffset = srcY * width * 4;
    const dstOffset = y * width * 4;
    flippedBuffer.set(buffer.subarray(srcOffset, srcOffset + width * 4), dstOffset);
  }

  // Convert pixel buffer to an image Blob
  const offscreenCanvas = document.createElement('canvas');
  offscreenCanvas.width = width;
  offscreenCanvas.height = height;
  const ctx = offscreenCanvas.getContext('2d');
  const imageData = ctx.createImageData(width, height);
  imageData.data.set(flippedBuffer);
  ctx.putImageData(imageData, 0, 0);

  offscreenCanvas.toBlob((blob) => {
    if (blob) {
      window.lastDroneBlob = blob;
    }
  }, 'image/jpeg', 0.7);

  // Restore original render target
  renderer.setRenderTarget(originalRenderTarget);

  updateInfo();
}

animate();
