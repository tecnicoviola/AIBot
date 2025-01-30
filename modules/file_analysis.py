import google.generativeai as genai
from modules.database import files_collection
from telethon import events
import configparser
from datetime import datetime
from PIL import Image
from io import BytesIO
import base64
import pdfplumber
import os
import magic  # For MIME type detection

# Load Configurations
config = configparser.ConfigParser()
config.read('config.ini')
GEMINI_API_KEY = config.get('default', 'gemini_api_key')

# Initialize Gemini AI
genai.configure(api_key=GEMINI_API_KEY)

# Helper function to process PDFs
def analyze_pdf(file_path):
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() + "\n"
            return full_text.strip() if full_text.strip() else "No text found in the PDF."
    except Exception as e:
        print(f"Error processing PDF: {e}")
        return "Error extracting text from PDF."

# Function to break large text into chunks
def split_text_into_chunks(text, max_length=4096):
    # Split text into chunks that fit within Telegram's message length limit
    chunks = []
    while len(text) > max_length:
        idx = text.rfind('\n', 0, max_length)  # Try to split at the last newline within the limit
        chunks.append(text[:idx])
        text = text[idx+1:]  # Remaining text
    chunks.append(text)  # Add the remainder of the text
    return chunks

async def analyze_file(event):
    chat_id = event.chat_id

    # Create directories if they don't exist
    os.makedirs("data/images", exist_ok=True)
    os.makedirs("data/pdfs", exist_ok=True)

    # Handle photos (images) and documents separately
    if event.message.photo:
        # For photos, generate a unique filename
        file_name = f"image_{event.message.id}.png"  # Use message ID as a unique identifier
        file_path = os.path.join("data/images", file_name)
    elif event.message.document:
        # For documents, use the original filename or generate a unique one
        file_name = event.message.file.name or f"file_{event.message.file.id}"
        file_path = os.path.join("data/pdfs" if event.message.document.mime_type == "application/pdf" else "data/images", file_name)
    else:
        # Unsupported file type
        await event.respond("Unsupported file type. Please upload a PDF or an image (JPG, PNG).")
        return

    # Download the file directly to the target directory
    await event.message.download_media(file=file_path)

    # Detect the MIME type of the file
    mime = magic.Magic(mime=True)
    mime_type = mime.from_file(file_path)

    # Check if it's an image or PDF based on MIME type
    if mime_type.startswith('image/'):
        # Process image files
        try:
            with open(file_path, "rb") as f:
                file_content = f.read()

            # Convert the byte content to a PIL Image
            image = Image.open(BytesIO(file_content))

            # Convert the PIL Image to a base64-encoded string
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            # Create a dictionary with the image data in the required format
            image_data = {
                "mime_type": "image/png",
                "data": image_base64
            }

            # Extract the user's text prompt from the message
            user_prompt = event.message.text if event.message.text else "Describe this image and any text in it."

            # Pass the image data and user's text prompt to the Gemini AI model
            model = genai.GenerativeModel("models/gemini-1.5-flash-latest")
            response = model.generate_content([user_prompt, image_data])

            # Store file metadata in MongoDB
            files_collection.insert_one({
                "chat_id": chat_id,
                "filename": file_name,
                "description": response.text,
                "timestamp": datetime.now()
            })

            # Send the analysis result back to the user
            await event.respond(f"🖼️ Image Analysis:\n{response.text}")

        except Exception as e:
            # Handle the case where the image can't be processed
            print(f"Error processing image: {e}")
            await event.respond("Oops! Something went wrong with the image upload. Please try again.")

    elif mime_type == 'application/pdf':
        # Process PDF files
        try:
            description = analyze_pdf(file_path)

            # Store file metadata in MongoDB
            files_collection.insert_one({
                "chat_id": chat_id,
                "filename": file_name,
                "description": description,
                "timestamp": datetime.now()
            })

            # Split the description if it's too long
            chunks = split_text_into_chunks(description)
            for chunk in chunks:
                await event.respond(f"📄 PDF Analysis:\n{chunk}")

        except Exception as e:
            # Handle errors with PDF processing
            print(f"Error processing PDF: {e}")
            await event.respond("Oops! Something went wrong with the PDF upload. Please try again.")

    else:
        # Unsupported file type
        await event.respond("Unsupported file type. Please upload a PDF or an image (JPG, PNG).")