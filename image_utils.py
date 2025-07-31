# image_utils.py
import fitz  # PyMuPDF
from PIL import Image
import io

def pdf_page_to_pil(page, scale=2.0):
    """
    Converts a fitz.Page (PyMuPDF) object to a PIL image.
    
    Parameters:
        page: fitz.Page object
        scale: float scaling factor (e.g., 2.0 for 2x zoom)

    Returns:
        PIL.Image.Image object
    """
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img
