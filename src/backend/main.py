import hashlib
import json
import logging
import os
import time
from tempfile import NamedTemporaryFile
from typing import AsyncGenerator, List

import openai
import pymupdf  # PyMuPDF for PDF processing
import pytesseract
from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from openai import OpenAI as OpenAIClient
from openai.types.chat import ChatCompletion
from starlette.responses import StreamingResponse

from prompts import UseCase, SYSTEM_PROMPTS

CACHE_DIR = ".file_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Load environment variables from .env file
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

client = OpenAIClient()

app = FastAPI()
# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Adjust path to your Tesseract data if needed
os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/Cellar/tesseract/5.5.0/share/tessdata"


### Helper Functions ###
def extract_text_from_image(image_path):
    try:
        with Image.open(image_path) as img:
            return pytesseract.image_to_string(img)
    except Exception as e:
        print(f"Error during OCR processing: {e}")
        return ""


def extract_markdown_from_pdf(file_path: str, document_name: str) -> str:
    markdown_content = []
    try:
        doc = pymupdf.open(file_path)  # Open the PDF using PyMuPDF

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("markdown")
            if text.strip():
                markdown_content.append(f"[{document_name} Page {page_num + 1}]\n{text}")

            images_in_page = page.get_images(full=True)
            for img_index, img in enumerate(images_in_page):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                with NamedTemporaryFile(suffix=f".{image_ext}") as temp:
                    temp.write(image_bytes)
                    temp.seek(0)
                    image_text = extract_text_from_image(temp.name)
                    if image_text.strip():
                        markdown_content.append(f"[{document_name} Page {page_num + 1}] {image_text}")

        doc.close()
        return "\n".join(filter(None, markdown_content))

    except Exception as e:
        print(f"Error processing PDF: {e}")
        return ""


# Cache for processed files
file_cache = {}


def get_file_hash(file: UploadFile) -> str:
    """
    Generate a hash for a file based on its content without consuming the stream.
    """
    file.file.seek(0)  # Ensure the stream is at the beginning
    hasher = hashlib.sha256()
    hasher.update(file.file.read())
    file.file.seek(0)  # Reset stream pointer after reading
    return hasher.hexdigest()


def get_cached_or_process_file(file: UploadFile) -> str:
    """
    Retrieve the processed content from the persistent cache or process the file if not cached.
    """
    file_hash = get_file_hash(file)
    cache_path = os.path.join(CACHE_DIR, f"{file_hash}.txt")

    # Check if the processed content exists in the persistent cache
    if os.path.exists(cache_path):
        logging.info(f"Cache hit for file: {file.filename}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()

    # Process the file and cache the result
    logging.info(f"Cache miss for file: {file.filename}. Processing...")
    with NamedTemporaryFile(suffix=".pdf") as temp:
        temp.write(file.file.read())
        temp.seek(0)
        processed_content = extract_markdown_from_pdf(temp.name, file.filename)

        # Save processed content to cache
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(processed_content)

        file.file.seek(0)  # Reset file pointer after processing
        return processed_content

def cleanup_cache(expiration_days: int = 7):
    """
    Remove cache files older than the specified number of days.
    """
    now = time.time()
    expiration_time = expiration_days * 86400  # Convert days to seconds

    for file in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, file)
        if os.path.isfile(file_path):
            file_age = now - os.path.getmtime(file_path)
            if file_age > expiration_time:
                logging.info(f"Removing expired cache file: {file}")
                os.remove(file_path)


def combine_context_from_files(files: List[UploadFile]) -> str:
    """
    Combine processed content from all files, leveraging caching.
    """
    contexts = [get_cached_or_process_file(file) for file in files]
    return "\n---\n".join(contexts)


SYSTEM_NOTE = """
---
\n
Important note about your equations, or latex in general: 
- Use "$$" for latex expressions, e.g., "$$x^2$$" for x squared or $$6 \text{CO}_2 + 6 \text{H}_2\text{O} + \text{light energy} \rightarrow \text{C}6\text{H}{12}\text{O}_6 + 6 \text{O}_2$$ for photosynthesis.
\n
---
"""


def get_system_prompt(mode: UseCase) -> str:
    return SYSTEM_PROMPTS[mode] + SYSTEM_NOTE


### Endpoints ###
@app.get("/use_cases")
async def get_use_cases():
    return [{"id": mode.name, "name": mode.value} for mode in UseCase]


@app.get("/list_models")
async def list_models():
    return client.models.list()  # List available models


@app.post("/process_files")
async def process_files(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        processed_content = get_cached_or_process_file(file)
        results.append({"filename": file.filename, "content_preview": processed_content[:100]})

    return {"status": "success", "processed_files": results}



@app.post("/process_stream")
async def process_stream(mode: str = Form(...), files: List[UploadFile] = File(...)):
    try:
        mode_enum = UseCase[mode]
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid mode value")

    system_prompt = get_system_prompt(mode_enum)

    # Combine all PDFs into one annotated context
    uploaded_context = combine_context_from_files(files)
    user_prompt = f"User uploaded class content:\n-----\n{uploaded_context}"

    async def generate() -> AsyncGenerator[str, None]:
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=True,
            max_tokens=4200
        )

        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield json.dumps({
                    "content": chunk.choices[0].delta.content
                }) + "\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/process")
async def process_file(mode: str = Form(...), files: List[UploadFile] = File(...)):
    logging.debug(f"Received mode: {mode}")

    try:
        mode_enum = UseCase[mode]
    except KeyError:
        logging.error("Invalid mode value")
        raise HTTPException(status_code=400, detail="Invalid mode value")

    # Chunk long text to fit within token limits
    system_prompt = get_system_prompt(mode_enum)

    # Combine all PDFs into one annotated context
    uploaded_context = combine_context_from_files(files)
    user_prompt = f"User uploaded class content:\n-----\n{uploaded_context}"
    response: ChatCompletion = client.chat.completions.create(
        model="o1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=2400
    )

    # Combine results into a single output
    final_output = response.choices[0].message.content
    logging.debug(f"Final output generated: {final_output[:50]}...")
    return {"output": final_output}


@app.post("/process")
async def process_file(mode: str = Form(...), files: List[UploadFile] = File(...)):
    logging.debug(f"Received mode: {mode}")

    try:
        mode_enum = UseCase[mode]
    except KeyError:
        logging.error("Invalid mode value")
        raise HTTPException(status_code=400, detail="Invalid mode value")

    # Chunk long text to fit within token limits
    system_prompt = SYSTEM_PROMPTS[mode_enum]

    # Combine all PDFs into one annotated context
    uploaded_context = combine_context_from_files(files)
    user_prompt = f"User uploaded class content:\n-----\n{uploaded_context}"
    response: ChatCompletion = client.chat.completions.create(
        model="o1-preview",
        messages=[
            {"role": "user", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=2400
    )

    # Combine results into a single output
    final_output = response.choices[0].message.content
    logging.debug(f"Final output generated: {final_output[:50]}...")
    return {"output": final_output}
