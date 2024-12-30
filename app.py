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
    This endpoint receives JSON data with:
      - "goal" (a string),
      - optionally a base64 "image",
      - optionally "history",
      - optionally "previousPlan" (the old plan steps).
    Calls Gemini with that context and returns a JSON list of steps.
    If 'history' or 'previousPlan' is present, we treat it as a re-evaluation.
    """
    try:
        body = await request.json()
        goal = body.get("goal", "explore the city")

        # Optional re-evaluation context
        history = body.get("history", None)
        previous_plan = body.get("previousPlan", None)

        # Retrieve base64 image data (if provided)
        image_base64 = body.get("image", None)
        image_filepath = None
        file_attachment = None

        # If we got a base64 image, decode and save it
        if image_base64:
            image_data = base64.b64decode(image_base64)
            image_filepath = f"plan_image_{int(time.time())}.jpg"
            with open(image_filepath, 'wb') as f:
                f.write(image_data)
            file_attachment = genai.upload_file(image_filepath)
            print(f"Uploaded {image_filepath} to Gemini for context.")
        else:
            print("No base64 image provided for plan context.")

        # Base prompt
        plan_prompt = (
            f"You are an expert drone pilot. Your goal is: {goal}.\n"
            "Below is the current first-person-view image from the drone as an attachment. "
            "Use the context in the image to refine your plan.\n\n"
            "Output a set of steps to complete the goal. If you are unsure at a given step, "
            "just return 'Re-evaluate' for that step so you can ask again with better information.\n\n"
            "Return your answer in the following JSON schema:\n\n"
            "[\n"
            "  {\n"
            "    \"step_number\": 1,\n"
            "    \"step_description\": \"Describe step 1\"\n"
            "  },\n"
            "  {\n"
            "    \"step_number\": 2,\n"
            "    \"step_description\": \"Describe step 2\"\n"
            "  },\n"
            "  ...\n"
            "]\n\n"
            "Only return valid JSON that matches this schema."
        )

        # If there's a history/previousPlan, let's modify the prompt to incorporate re-evaluation
        if history or previous_plan:
            plan_prompt = (
                "You are in RE-EVALUATION mode due to new information or updated context.\n"
                f"Existing history of what has been seen:\n{history if history else '(No history yet)'}\n"
                f"Previous plan: {previous_plan if previous_plan else '(No plan yet)'}\n\n"
                + plan_prompt
            )

        if file_attachment:
            plan_result = model.generate_content([file_attachment, "\n\n", plan_prompt])
        else:
            plan_result = model.generate_content(plan_prompt)

        plan_text = plan_result.text

        # Try to parse the returned text as JSON
        try:
            cleaned_text = re.sub(r'```(\w+)?', '', plan_text).strip()
            plan = json.loads(cleaned_text)
        except json.JSONDecodeError:
            # If Gemini didn't return valid JSON
            return JSONResponse(
                {
                    "error": "Gemini did not return valid JSON.",
                    "rawOutput": plan_text
                },
                status_code=500
            )

        # Clean up the temporary file
        if image_filepath and os.path.exists(image_filepath):
            os.remove(image_filepath)

        return JSONResponse({"planSteps": plan})

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/generate_history")
async def generate_history(request: Request):
    """
    This endpoint updates the 'history' by describing the current FPV (image),
    referencing what we've seen so far (if provided), and optionally including
    the last drone movement. It returns the updated history in JSON form.
    
    The response from Gemini/your LLM must:
      1. Return valid JSON matching the schema:
         [
           {
             "history_id": "history view 1",
             "description": "2 short but highly information-dense sentences"
           },
           {
             "history_id": "history view 2",
             "description": "2 short but highly information-dense sentences"
           }
         ]
      2. Contain only 2 short but highly information-dense sentences for each
         new FPV view. The model may modify or update existing entries if
         needed for consistency or clarity.
    """
    try:
        body = await request.json()
        current_history = body.get("history", "")  # existing history text
        last_movement = body.get("lastMovement", "")  # e.g. "fly x,y 2 meters"
        image_base64 = body.get("image", None)

        image_filepath = None
        file_attachment = None

        # Handle the image, if provided
        if image_base64:
            image_data = base64.b64decode(image_base64)
            image_filepath = f"plan_image_{int(time.time())}.jpg"
            with open(image_filepath, 'wb') as f:
                f.write(image_data)
            file_attachment = genai.upload_file(image_filepath)
            print(f"Uploaded {image_filepath} to Gemini for context.")
        else:
            print("No base64 image provided for plan context.")

        # ----- Build the prompt -----
        if current_history:
            # Prompt when current_history exists
            prompt = (
                "You are an expert drone pilot. This is your current view.\n"
                f"This is what you have already seen - your history: {current_history}\n\n"
                "Describe, in relation to what you’ve already seen, your current view and append it "
                "to the end of your 'history'. Also, based on what you currently see, update your history "
                "so that it is consistent with a drone's flight path.\n\n"
                "Important: Only return 2 short but highly information-dense sentences for each new FPV. "
                "You may add or modify the existing 2 sentences if necessary.\n\n"
                "Return your answer in the following JSON schema:\n\n"
                "[\n"
                "  {\n"
                "    \"history_id\": \"history view 1\",\n"
                "    \"description\": \"2 short but highly information-dense sentences\"\n"
                "  },\n"
                "  {\n"
                "    \"history_id\": \"history view 2\",\n"
                "    \"description\": \"2 short but highly information-dense sentences\"\n"
                "  }\n"
                "]\n\n"
                "Only return valid JSON that matches this schema."
            )
        else:
            # Prompt when there is NO existing history
            prompt = (
                "You are an expert drone pilot. This is your current view.\n"
                "Describe your current view.\n"
                "Important: Only return 2 short but highly information-dense sentences.\n\n"
                "Return your answer in the following JSON schema:\n\n"
                "[\n"
                "  {\n"
                "    \"history_id\": \"history view 1\",\n"
                "    \"description\": \"2 short but highly information-dense sentences\"\n"
                "  }\n"
                "]\n\n"
                "Only return valid JSON that matches this schema."
            )

        # If we have a last movement, include it in the prompt
        if last_movement:
            prompt += f"\nAlso, this is the last flight path you just finished: \"{last_movement}\""

        # ----- Call your model/gemini -----
        # If you support passing file context + text, do so. Otherwise just pass the prompt.
        if file_attachment:
            # Example: pass both the uploaded file and prompt if your system supports it
            # For demonstration: we'll just pass the prompt
            result = model.generate_content([file_attachment, "\n\n",  prompt])
        else:
            result = model.generate_content(prompt)

        # The model is expected to return JSON text in the structure described
        updated_history = result.text

        print(f"[generate_history] Model response: {updated_history}")

        # Clean up temporary image file
        if image_filepath and os.path.exists(image_filepath):
            os.remove(image_filepath)

        # ----- Return the final JSON -----
        # Make sure the model output is valid JSON.
        try:
            cleaned_text = re.sub(r'```(\w+)?', '', updated_history).strip()
            updated_history_json = json.loads(cleaned_text)
        except json.JSONDecodeError:
            # Handle invalid JSON gracefully
            return JSONResponse(
                {"error": "Model output was not valid JSON", "rawOutput": updated_history},
                status_code=500
            )

        return JSONResponse(updated_history_json)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.websocket("/feed")
async def websocket_feed(websocket: WebSocket):
    """
    WebSocket used for:
      - Receiving TEXT messages: e.g. {"goal": "..."} or {"completeStep": true}.
      - Receiving BINARY frames: treat as images -> bounding box detection.
    We now also incorporate the current 'history' in the prompt if available.
    """
    await websocket.accept()
    print("WebSocket connection accepted")

    global current_goal
    global history_text
    global current_step_index

    frame_counter = 0
    first_image_received = False

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
                arr = np.frombuffer(frame_data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    # Flip if needed
                    img = cv2.flip(img, 0)

                    filename = f"frame_{int(time.time())}_{frame_counter}.jpg"
                    cv2.imwrite(filename, img)
                    print(f"Received and saved frame {frame_counter} as {filename}")
                    frame_counter += 1

                    # Build the bounding box prompt
                    if not current_goal:
                        # If no goal is set, skip bounding box
                        bounding_box = []
                    else:
                        # Include the history in the prompt if not first call
                        if history_text.strip():
                            bounding_box_prompt = (
                                "You are an expert drone pilot.\n"
                                "You have already been flying and this is the history for what you have seen:\n"
                                f"{history_text}\n\n"
                                "Now, the current goal/step is:\n"
                                f"{current_goal}\n"
                                "Generate a bounding box in the form of [ymin, xmin, ymax, xmax] for where you want the drone to fly.\n"
                                "Be very conservative with your box so as to minimize the chance you hit any objects.\n"
                                "Return the smallest box possible to achieve the step.\n"
                                "Give your explanation first, then the coordinates in the last line."
                            )
                        else:
                            # First call, no prior history
                            bounding_box_prompt = (
                                "You are an expert drone pilot.\n"
                                "This is the first time you've seen this environment, no prior history is available.\n"
                                f"The current goal/step is:\n{current_goal}\n"
                                "Generate a bounding box in the form of [ymin, xmin, ymax, xmax] for where you want the drone to fly.\n"
                                "Be very conservative with your box so as to minimize the chance you hit any objects.\n"
                                "Return the smallest box possible to achieve the step.\n"
                                "Give your explanation first, then the coordinates in the last line."
                            )

                        myfile = genai.upload_file(filename)
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

                    # We could also update 'history_text' here or rely on /generate_history
                    # But let's keep it separate as per your new flow.

                    # Return bounding box + updated step index to client
                    await websocket.send_json({
                        "bounding_box": bounding_box,
                        "history": history_text,  # We'll rely on /generate_history for actual updates
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
        # ws_ping_interval=60,
        # ws_ping_timeout=60
    )
