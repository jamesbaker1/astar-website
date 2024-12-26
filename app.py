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

# Import Google Generative AI Python library (ensure you've installed `google-generativeai`)
import google.generativeai as genai

# Initialize or configure the Gemini model
# Make sure you've set your credentials/environment variables appropriately
model = genai.GenerativeModel("gemini-1.5-flash")

app = FastAPI()

@app.websocket("/feed")
async def websocket_feed(websocket: WebSocket):
    """
    This WebSocket endpoint expects the FIRST TEXT message to contain JSON with a 'goal' field.
    Subsequent messages should be binary images (frames) that we send to the Gemini model,
    along with the 'goal' from the first message.
    """
    await websocket.accept()
    print("WebSocket connection accepted")

    try:
        # 1) Receive the first TEXT message, containing JSON with 'goal'
        initial_message = await websocket.receive_text()
        data = json.loads(initial_message)
        goal = data.get("goal", "go into the next room")
        print(f"Received goal: {goal}")
    except Exception as e:
        print("Could not read the initial goal message:", e)
        await websocket.close()
        return

    frame_counter = 0

    while True:
        try:
            # 2) After the first message, we expect BINARY frames (JPEG data)
            frame_data = await websocket.receive_bytes()

            # Convert bytes to a NumPy array
            arr = np.frombuffer(frame_data, np.uint8)

            # Decode the image
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            if img is not None:
                # Save the frame to disk (optionally) for verification + sending to Gemini
                filename = f"frame_{int(time.time())}_{frame_counter}.jpg"
                cv2.imwrite(filename, img)
                print(f"Received and saved frame {frame_counter} as {filename}")
                frame_counter += 1

                # -- CALL GEMINI API HERE --
                # Upload the file you just saved
                myfile = genai.upload_file(filename)
                
                # Construct your prompt, incorporating the dynamic goal
                prompt = (
                    "You are an expert drone pilot. The view is the drone's first-person view in the air. "
                    f"Your goal is to {goal}. "
                    "Generate a plan to complete this goal. "
                    "Based on this plan, return a bounding box in the form of [ymin, xmin, ymax, xmax] "
                    "for where you want the drone to fly. "
                    "Give your explanation first before you return the coordinates."
                )

                # Generate the content using the model
                result = model.generate_content([
                    myfile, 
                    "\n\n", 
                    prompt
                ])

                # result.text will contain the explanation + bounding box
                gemini_response = result.text
                print(f"Gemini response: {gemini_response}")

                # PARSE BOUNDING BOX
                # Looking for something like [10, 20, 200, 400]
                bbox_match = re.search(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", gemini_response)
                if bbox_match:
                    ymin, xmin, ymax, xmax = bbox_match.groups()
                    bounding_box = [int(ymin), int(xmin), int(ymax), int(xmax)]
                else:
                    # If we can't find a bounding box, send an empty array
                    bounding_box = []

                # -- SEND BOUNDING BOX BACK OVER THE WEBSOCKET --
                await websocket.send_json({"bounding_box": bounding_box})
            else:
                print("Received data but could not decode as an image.")

        except WebSocketDisconnect:
            print("WebSocket client disconnected.")
            break
        except Exception as e:
            print("WebSocket connection closed due to error:", e)
            break

# Serve the static files at /public
app.mount("/", StaticFiles(directory="public", html=True), name="public")

# Define a GET endpoint at "/" to return demo.html
@app.get("/")
async def root():
    return FileResponse("public/demo.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
