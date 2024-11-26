import json

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from typing import List, AsyncGenerator
import openai
import os
from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletion
from starlette.responses import StreamingResponse

from prompts import UseCase, SYSTEM_PROMPTS
import logging

load_dotenv()  # Load environment variables from .env file
openai.api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI()

app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.DEBUG)


@app.get("/use_cases")
async def get_use_cases():
    return [{"id": mode.name, "name": mode.value} for mode in UseCase]


@app.get("/list_models")
async def list_models():
    return client.models.list()  # List available models


@app.post("/process")
async def process_file(uploaded_context: str = Form(...), mode: str = Form(...)):
    logging.debug(f"Received mode: {mode}")

    try:
        mode_enum = UseCase[mode]  # Convert string to UseCase enum
    except KeyError:
        logging.error("Invalid mode value")
        raise HTTPException(status_code=400, detail="Invalid mode value")

    # Chunk long text to fit within token limits
    system_prompt = SYSTEM_PROMPTS[mode_enum]

    user_prompt = f"User uploaded class content: \n ----- \n {uploaded_context}"
    response: ChatCompletion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_completion_tokens=2400,
    )

    # Combine results into a single output
    final_output = response.choices[0].message.content

    logging.debug(f"Final output generated: {final_output[:500]}...")  # Log first 500 chars of the output
    return {"output": final_output}


@app.post("/process_stream")
async def process_stream(uploaded_context: str = Form(...), mode: str = Form(...)):
    try:
        mode_enum = UseCase[mode]
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid mode value")

    system_prompt = SYSTEM_PROMPTS[mode_enum]
    user_prompt = f"User uploaded class content: \n ----- \n {uploaded_context}"

    async def generate() -> AsyncGenerator[str, None]:
        stream = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=True,
            max_tokens=2400
        )

        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield json.dumps({
                    "content": chunk.choices[0].delta.content
                }) + "\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
