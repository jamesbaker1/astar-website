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

import google.generativeai as genai

# Configure the Gemini model
genai.configure(api_key="AIzaSyD6dke9yd-dmZoNmGhXdVEhQFIjkb0sxXY")
model = genai.GenerativeModel("gemini-2.0-flash-exp")

app = FastAPI()

# Global state for a simple demo (or you can store in a session)
current_goal = None
history_text = ""
current_step_index = 0

@app.post("/get_plan")
async def get_plan(request: Request):
    """
    This endpoint receives JSON data with a "goal", calls Gemini to get a plan,
    returns that plan as a list of steps. The front-end can call this
    separately (via fetch or axios).
    """
    try:
        body = await request.json()
        goal = body.get("goal", "go into the next room")

        plan_prompt = (
            "You are an expert drone pilot. Your goal is to: "
            f"{goal}.\n"
            "Output a set of steps to complete the goal. If you are unsure at a given step, "
            "just return 'reevaluate' for that step so you can ask again with better information."
        )

        plan_result = model.generate_content(plan_prompt)
        plan_text = plan_result.text

        # Naive parse of steps by splitting on new lines
        steps = []
        for line in plan_text.split('\n'):
            line = line.strip()
            if line:
                steps.append(line)

        return JSONResponse({"planSteps": steps})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.websocket("/feed")
async def websocket_feed(websocket: WebSocket):
    """
    WebSocket used for:
      - Receiving TEXT messages: e.g. {"goal": "..."} or {"completeStep": true}.
      - Receiving BINARY frames: treat as images -> bounding box detection + history update.

    We do NOT forcibly close the WebSocket after receiving the first message.
    We keep reading messages until the client closes or an error occurs.
    """
    await websocket.accept()
    print("WebSocket connection accepted")

    global current_goal
    global history_text
    global current_step_index

    frame_counter = 0

    while True:
        try:
            message = await websocket.receive()

            # 1. If the client disconnects
            if message["type"] == "websocket.disconnect":
                print("WebSocket client disconnected.")
                break

            # 2. If the message is TEXT
            if "text" in message:
                try:
                    text_msg = message["text"]
                    data = json.loads(text_msg)

                    # If the user updated the "goal" (which could be a step or sub-goal)
                    if "goal" in data:
                        current_goal = data["goal"]
                        print(f"Updated (sub)goal on the WebSocket feed: {current_goal}")

                    # If the user wants to mark a step completed
                    if "completeStep" in data and data["completeStep"] == True:
                        current_step_index += 1
                        print(f"Step completed. Now current_step_index = {current_step_index}")
                        # Notify the client
                        await websocket.send_json({"currentStepIndex": current_step_index})

                except json.JSONDecodeError:
                    print("Received text but not valid JSON. Ignoring.")
                except Exception as e:
                    print("Error processing text message:", e)

            # 3. If the message is BINARY (i.e., an image)
            if "bytes" in message:
                frame_data = message["bytes"]

                # Convert bytes to a NumPy array
                arr = np.frombuffer(frame_data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    # Flip vertically if needed
                    img = cv2.flip(img, 0)

                    filename = f"frame_{int(time.time())}_{frame_counter}.jpg"
                    cv2.imwrite(filename, img)
                    print(f"Received and saved frame {frame_counter} as {filename}")
                    frame_counter += 1

                    # ---- CALL GEMINI FOR BOUNDING BOX (Given current_goal) ----
                    # If no goal is set yet, we can skip or set a default
                    if not current_goal:
                        # No valid goal => do nothing
                        bounding_box = []
                    else:
                        # e.g. "step_prompt" might be your 'current_goal'
                        step_prompt = current_goal

                        myfile = genai.upload_file(filename)
                        bounding_box_prompt = (
                            "You are an expert drone pilot. The view is the drone's first-person view in the air.\n"
                            f"Your current step is: {step_prompt}.\n"
                            "Generate a bounding box in the form of [ymin, xmin, ymax, xmax] for where you want the drone to fly.\n"
                            "Be very conservative with your box so as to minimize the chance you hit any objects. "
                            "Return the smallest box possible to achieve the step.\n"
                            "Give your explanation first, then the coordinates in the last line."
                        )
                        result_for_box = model.generate_content([myfile, "\n\n", bounding_box_prompt])
                        gemini_response_for_box = result_for_box.text
                        print(f"[Bounding Box] Gemini response: {gemini_response_for_box}")

                        # Attempt to parse bounding box
                        bbox_match = re.search(
                            r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]",
                            gemini_response_for_box
                        )
                        if bbox_match:
                            ymin, xmin, ymax, xmax = bbox_match.groups()
                            bounding_box = [int(ymin), int(xmin), int(ymax), int(xmax)]
                        else:
                            bounding_box = []

                    # ---- CALL GEMINI FOR HISTORY (based on this new image) ----
                    history_prompt = (
                        "You are an expert drone pilot. This is your current view. "
                        "Output a description of what you have seen that would be helpful "
                        "for a pilot who cannot see your first person view.\n"
                        f"Your history up until this point is: {history_text}\n"
                    )
                    result_for_history = model.generate_content([myfile, "\n\n", history_prompt])
                    gemini_response_for_history = result_for_history.text
                    print(f"[History] Gemini response: {gemini_response_for_history}")

                    # Append new info to running history
                    history_text += f"\n{gemini_response_for_history}\n"

                    # Return bounding box + updated history to client
                    await websocket.send_json({
                        "bounding_box": bounding_box,
                        "history": history_text,
                        "currentStepIndex": current_step_index
                    })
                else:
                    print("Received data, but could not decode as an image.")

        except WebSocketDisconnect:
            print("WebSocket disconnected.")
            break
        except Exception as e:
            print("Error in WebSocket loop:", e)
            break


# Serve static files
app.mount("/", StaticFiles(directory="public", html=True), name="public")

@app.get("/")
async def root():
    return FileResponse("public/demo.html")

if __name__ == "__main__":
    # Increase timeouts to help keep the socket alive if desired
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        # WebSocket ping intervals can be tweaked:
        # ws_ping_interval=60,
        # ws_ping_timeout=60
    )
