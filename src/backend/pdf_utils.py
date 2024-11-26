import pytesseract
from PIL import Image


def extract_text_from_image(image_path):
    return pytesseract.image_to_string(Image.open(image_path))


def chunk_text(text, max_length=2000):
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_length):
        chunks.append(" ".join(words[i:i + max_length]))
    return chunks
