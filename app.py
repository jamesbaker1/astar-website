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
genai.configure(api_key="AIzaSyD6dke9yd-dmZoNmGhXdVEhQFIjkb0sxXY")
model = genai.GenerativeModel("gemini-2.0-flash-exp")

app = FastAPI()

@app.get("/")
async def root():
    return FileResponse("public/demo.html")


@app.websocket("/feed")
async def websocket_feed(websocket: WebSocket):
    """
    A stateless WebSocket endpoint that expects a single TEXT message
    containing JSON with:
      - goal (string)
      - history (list of strings, each with 2 short sentences)
      - image (base64-encoded)

    Then:
      1. Decode the base64 image and save to disk.
      2. Generate bounding box => send bounding_box message.
      3. Generate updated history => send history message (now just an array of strings).
      4. Loop until the client disconnects.
    """
    await websocket.accept()
    print("WebSocket connection accepted (stateless mode)")

    while True:
        try:
            # 1) Wait for text from the client (JSON)
            raw_message = await websocket.receive_text()
            data = json.loads(raw_message)

            # 2) Parse fields: goal, history, base64 image
            goal = data.get("goal", "")
            history_data = data.get("history", [])  # list of strings
            image_base64 = data.get("image", None)

            if not goal:
                print("[Warning] No goal provided in message.")
            if not image_base64:
                print("[Warning] No base64 image provided.")

            # 3) Decode the base64 image to a local file (if provided)
            filename = None
            if image_base64:
                try:
                    image_bytes = base64.b64decode(image_base64)
                    # Save to file
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

            # 4) Generate bounding box
            if filename and goal:
                bounding_box = await generate_bounding_box(filename, goal, history_data)
            else:
                bounding_box = []

            # Send bounding box to client immediately
            await websocket.send_json({
                "type": "bounding_box",
                "data": bounding_box
            })

            # 5) Generate updated history (array of strings)
            if filename:
                updated_history = await generate_updated_history(filename, history_data)
            else:
                updated_history = history_data or []

            # Send updated history to client
            await websocket.send_json({
                "type": "history",
                "data": updated_history
            })

            # 6) Clean up the local file
            # if filename and os.path.exists(filename):
            #     os.remove(filename)

        except WebSocketDisconnect:
            print("WebSocket disconnected.")
            break
        except Exception as e:
            print("Error in WebSocket loop:", e)
            break


async def generate_bounding_box(image_path: str, goal: str, history: list) -> list:
    """
    Generate a bounding box. Return in the form [ymin, xmin, ymax, xmax].
    If parsing fails, return an empty list.
    
    history is now just a list of 2-sentence strings.
    """
    # Convert history list -> string for the prompt
    # e.g. history = ["Two short sentences.", "Another vantage..."]
    if history:
        history_str = "\n".join([f"View {i}: {entry}" for i, entry in enumerate(history)])
    else:
        history_str = "No prior vantage data."

    # Build prompt
    bounding_box_prompt = (
        "You are an expert drone pilot.\n"
        f"Goal: {goal}\n\n"
        "Existing vantage descriptions (each is 2 sentences):\n"
        f"{history_str}\n\n"
        "Given the new image, generate a bounding box in the form of [ymin, xmin, ymax, xmax] "
        "where you want the drone to fly. Be very conservative to avoid collisions.\n"
        "Give an explanation, then the coordinates in the last line."
    )

    # Upload the file
    file_attachment = genai.upload_file(image_path)

    # Call Gemini
    result = model.generate_content([file_attachment, "\n\n", bounding_box_prompt])
    gemini_response = result.text
    print(f"[Bounding Box] Gemini response:\n{gemini_response}")

    # Parse bounding box
    bbox_match = re.search(
        r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]",
        gemini_response
    )
    if bbox_match:
        ymin, xmin, ymax, xmax = bbox_match.groups()
        return [int(ymin), int(xmin), int(ymax), int(xmax)]
    else:
        return []

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


async def generate_updated_history(image_path: str, current_history: list) -> list:
    """
    Generate or update the history with 2-sentence descriptions of the new FPV.
    Return your entire updated history as an array of strings.
    
    Each string is "2 short, highly information-dense sentences."
    The index in the array corresponds to the vantage number.
    """
    # Convert the existing list to a multiline string for the LLM prompt
    # e.g. current_history = ["Sentences for vantage #0", "Sentences for vantage #1"]
    if current_history:
        existing_history_str = "\n".join(
            [f"View {i}: {desc}" for i, desc in enumerate(current_history)]
        )
    else:
        existing_history_str = "(no prior vantage)"

    # Create the prompt
    # We ask the model to append a new vantage with exactly 2 short sentences to our history array.
    # Then return the ENTIRE updated array in valid JSON.
    if existing_history_str.strip() and existing_history_str.strip() != "(no prior vantage)":
        prompt = (
            "You are an expert drone pilot. This is your new FPV image.\n"
            "Your existing vantage descriptions (each is exactly 2 short sentences) are:\n"
            f"{existing_history_str}\n\n"
            "Describe this new vantage in exactly 2 short, highly information-dense sentences, "
            "and append it to the existing array of vantage descriptions.\n\n"
            "Return the entire updated array in **valid JSON** form, like:\n"
            '["Two short sentences for vantage #0","Two short sentences for vantage #1", ...]'
        )
    else:
        # If we have no prior vantage
        prompt = (
            "You are an expert drone pilot seeing your first FPV.\n"
            "Describe it in exactly 2 short, highly information-dense sentences.\n"
            "Return as a JSON array of a single string representing the two sentences, e.g.:\n"
            '["first sentence. second sentence."]'
        )

    # Upload the file
    file_attachment = genai.upload_file(image_path)
    result = model.generate_content([file_attachment, "\n\n", prompt])
    gemini_response = result.text
    print(f"[Generate History] Gemini response:\n{gemini_response}")

    # Clean up the LLM output (remove code fences, extra whitespace, etc.)
    cleaned_text = re.sub(r'```(\w+)?', '', gemini_response).strip()

    try:
        updated_history_list = json.loads(cleaned_text)
        # Ensure we got a list of strings
        if isinstance(updated_history_list, list) and all(isinstance(x, str) for x in updated_history_list):
            return updated_history_list
        else:
            print("LLM returned JSON, but not a list of strings. Using old history.")
            return current_history
    except json.JSONDecodeError:
        print("Invalid JSON from LLM for history. Returning old history.")
        return current_history


app.mount("/", StaticFiles(directory="public", html=True), name="public")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
