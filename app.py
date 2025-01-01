from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import cv2
import numpy as np
import time
import os
import re
import json
import base64

import google.generativeai as genai

# Configure Gemini
genai.configure(api_key="AIzaSyD6dke9yd-dmZoNmGhXdVEhQFIjkb0sxXY")  # Replace with your API key
model = genai.GenerativeModel("gemini-exp-1206")  # Or your desired model
# model = genai.GenerativeModel("gemini-2.0-flash-exp")

app = FastAPI()

@app.get("/")
async def root():
    return FileResponse("public/demo.html")

@app.websocket("/feed")
async def websocket_feed(websocket: WebSocket):
    """
    A stateful WebSocket endpoint that maintains a conversation with Gemini.
    Expects:
      - goal (initially)
      - image (base64-encoded, in subsequent messages)
    
    Then:
      1. Initialize or continue a chat session with Gemini.
      2. Send the image and prompt to Gemini.
      3. Receive Gemini's response. If it contains "GOAL COMPLETED", send a special
         message and exit. Otherwise, extract flight instruction from the response.
      4. Send the flight instruction to the client.
      5. Loop until the client disconnects or the goal is achieved.
    """
    await websocket.accept()
    print("WebSocket connection accepted (stateful mode)")

    chat = None  # Initialize chat session to None
    goal = "explore the city"  # default
    try:
        while True:
            # 1) Wait for text from the client (JSON)
            raw_message = await websocket.receive_text()
            data = json.loads(raw_message)

            # 2) Parse fields: goal (initial), base64 image (always)
            image_base64 = data.get("image", None)
            new_goal = data.get("goal", None)

            # Override with new goal if provided
            if new_goal:
                goal = new_goal

            if not image_base64:
                print("[Warning] No base64 image provided.")
                await websocket.send_json({
                    "type": "error",
                    "message": "No base64 image provided"
                })
                continue

            # 3) Decode the base64 image to a local file
            filename = None
            if image_base64:
                try:
                    image_bytes = base64.b64decode(image_base64)
                    filename = f"frame_{int(time.time())}.jpg"
                    with open(filename, "wb") as f:
                        f.write(image_bytes)
                    print(f"Decoded image written to: {filename}")
                except Exception as e:
                    print(f"Error decoding base64 image: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Could not decode base64 image"
                    })
                    continue
            
            # 4) Initialize or continue chat session
            if chat is None:
                chat = model.start_chat(history=[])
            
            # 5) Create prompt
            flight_prompt = (
                "You are an expert drone pilot. The image is the drone's first person view. "
                f"Your goal is to: {goal}. Explain yourself before you output an action and try to describe where you want the drone to go before you generate a bounding box. Make the bounding box and distance as conservative as possible to avoid hitting any objects. if you hit an object, someone may die. "
                "You have three possible flight actions to accomplish the goal:\n"
                "1) Rotate => {\"r\": <angle_degrees (your field of view is 90 degrees - left turn is negative angle and right turn is positive angle)>}\n"
                "2) Elevate => {\"e\": <meters_up>}\n"
                "3) Go to bounding box => {\"g\": [ymin, xmin, ymax, xmax], \"distance\": <meters>}\n\n"
                "Choose exactly one flight option\n\n"
                "If you believe you have accomplished your goal simply return GOAL COMPLETED."
            )

            # 6) Send image and prompt to Gemini in the chat thread
            file_attachment = genai.upload_file(filename)
            parts = [file_attachment, flight_prompt]
            print(f"Sending prompt to Gemini:\n{flight_prompt}")
            response = chat.send_message(parts)

            # 7) Get Gemini's raw response
            gemini_response = response.text
            print(f"[Flight Instruction] Gemini response:\n{gemini_response}")

            # Check for "GOAL COMPLETED" first
            if "GOAL COMPLETED" in gemini_response.upper():
                # Send a special message to the client
                await websocket.send_json({
                    "type": "goal_completed",
                    "message": "Gemini indicates that the goal has been accomplished."
                })
                # Clean up, then break out of the loop
                if filename and os.path.exists(filename):
                    os.remove(filename)
                break
            
            # 8) Otherwise, proceed to extract flight instruction from Gemini's response
            flight_instruction = extract_flight_instruction(gemini_response)

            # 9) Send flight instruction to the client
            await websocket.send_json({
                "type": "flight_instruction",
                "data": flight_instruction
            })
            
            # 10) Clean up the local image file
            # if filename and os.path.exists(filename):
            #     os.remove(filename)

            # 11) Check for empty flight_instruction => no valid action found
            if not flight_instruction:
                print("Goal achieved or invalid response. Exiting.")
                break

    except WebSocketDisconnect:
        print("WebSocket disconnected.")
    except Exception as e:
        print("Error in WebSocket loop:", e)

def extract_flight_instruction(gemini_response: str) -> dict:
    """
    Extracts the flight instruction JSON from Gemini's response.
    Returns {} if no valid instruction is found.
    """
    match = re.search(r"\{.*?\}", gemini_response, re.DOTALL)
    if not match:
        return {}
    # print(dict(match.group(0)))
    try:
        flight_dict = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}

    # Validate that only one valid key is present
    valid_keys = {"r", "e", "g"}
    keys_present = [k for k in flight_dict.keys() if k in valid_keys]
    if len(keys_present) != 1:
        return {}

    # If the single valid key is "g", we expect: "g": [ [ymin, xmin, ymax, xmax], distance ]
    if "g" in flight_dict:
        bbox = flight_dict["g"]
        distance = flight_dict["distance"]
        
        # Convert bounding box to its center
        center = get_bbox_center(bbox)
        # Replace the original g with the processed version: [center, distance]
        flight_dict["g"] = [center, distance]
        print(flight_dict)

    return flight_dict

def get_bbox_center(bbox):
    """
    Given [ymin, xmin, ymax, xmax] in the range [0..1000],
    compute the center [x_center, y_center] in normalized coordinates.
    """
    ymin, xmin, ymax, xmax = bbox

    # Normalize each coordinate
    ymin_norm = ymin / 1000.0
    xmin_norm = xmin / 1000.0
    ymax_norm = ymax / 1000.0
    xmax_norm = xmax / 1000.0

    # Compute center in normalized coordinates
    x_center = (xmin_norm + xmax_norm) / 2.0
    y_center = (ymin_norm + ymax_norm) / 2.0

    return [x_center, y_center]

# Mount the static files (public/demo.html, etc.)
app.mount("/", StaticFiles(directory="public", html=True), name="public")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
