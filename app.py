from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import cv2
import numpy as np
import time
import os
import re
import json

import google.generativeai as genai

# Initialize or configure the Gemini model
genai.configure(api_key="AIzaSyD6dke9yd-dmZoNmGhXdVEhQFIjkb0sxXY")
model = genai.GenerativeModel("gemini-2.0-flash-exp")

app = FastAPI()

@app.websocket("/feed")
async def websocket_feed(websocket: WebSocket):
    """
    This WebSocket endpoint:
      1) Awaits a TEXT message with a 'goal'.
      2) Then for each BINARY (JPEG) image it receives:
         - calls Gemini
         - returns bounding box.
    The client can choose to only send new frames when it's *ready* for new guidance.
    """
    await websocket.accept()
    print("WebSocket connection accepted")

    goal = None

    try:
        # 1) First message must be TEXT containing JSON with 'goal'
        initial_message = await websocket.receive_text()
        data = json.loads(initial_message)
        goal = data.get("goal", "go into the next room")
        print(f"Received goal: {goal}")
    except Exception as e:
        print("Could not read the initial goal message:", e)
        await websocket.close()
        return

    frame_counter = 0

    try:
        while True:
            message = await websocket.receive()
            
            # If the client closes or disconnects
            if message["type"] == "websocket.disconnect":
                print("WebSocket client disconnected.")
                break
            
            # If we got TEXT again, maybe the client updated the goal
            if "text" in message:
                try:
                    text_msg = message["text"]
                    data = json.loads(text_msg)
                    if "goal" in data:
                        goal = data["goal"]
                        print(f"Updated goal: {goal}")
                except json.JSONDecodeError:
                    print("Received text but not valid JSON. Ignoring.")
            
            # If we got BINARY data, treat it as an image
            if "bytes" in message:
                frame_data = message["bytes"]

                # Convert bytes to NumPy array
                arr = np.frombuffer(frame_data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if img is not None:
                    # Flip the image vertically to fix upside-down
                    img = cv2.flip(img, 0)

                    filename = f"frame_{int(time.time())}_{frame_counter}.jpg"
                    cv2.imwrite(filename, img)
                    print(f"Received and saved frame {frame_counter} as {filename}")
                    frame_counter += 1

                    # --- CALL GEMINI API ---
                    # Upload file to Gemini
                    myfile = genai.upload_file(filename)

                    # Construct your prompt
                    prompt = (
                        "You are an expert drone pilot. The view is the drone's first-person view in the air. "
                        f"Your goal is to {goal}. "
                        "Generate a plan to complete this goal. "
                        "Based on this plan, return a bounding box in the form of [ymin, xmin, ymax, xmax] "
                        "for where you want the drone to fly. Be very conservative with your box so as to minimize the chance you hit any objects. Return the smallest box possible to achieve the goal."
                        "Give your explanation first before you return the coordinates."
                    )

                    # Generate the content using the model
                    result = model.generate_content([myfile, "\n\n", prompt])
                    gemini_response = result.text
                    print(f"Gemini response: {gemini_response}")

                    # Attempt to parse bounding box
                    bbox_match = re.search(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", gemini_response)
                    if bbox_match:
                        ymin, xmin, ymax, xmax = bbox_match.groups()
                        bounding_box = [int(ymin), int(xmin), int(ymax), int(xmax)]
                    else:
                        bounding_box = []

                    # Send bounding box back over WS
                    await websocket.send_json({"bounding_box": bounding_box})
                else:
                    print("Received data, but could not decode as an image.")

    except WebSocketDisconnect:
        print("WebSocket disconnected.")
    except Exception as e:
        print("Error in WebSocket connection:", e)
    finally:
        await websocket.close()

# Serve static files
app.mount("/", StaticFiles(directory="public", html=True), name="public")

@app.get("/")
async def root():
    return FileResponse("public/demo.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
