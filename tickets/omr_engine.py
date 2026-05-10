import json
import base64
import google.generativeai as genai
from django.conf import settings

# Configure Gemini with the API key from settings
genai.configure(api_key=settings.GEMINI_API_KEY)

def analyze_jrf_image(image_bytes):
    """
    Accepts raw image bytes, sends it to Gemini 1.5 Flash, 
    and returns a parsed JSON dictionary.
    """
    try:
        # Define the exact prompt requested by the user
        prompt = (
            "You are a strict data extraction assistant. Analyze this scanned Job Request Form. \n"
            "1. Find the 'Ticket ID' text (usually starts with TKT- or just a number). \n"
            "2. Look at the Performance Indicator table. Tell me which number (1 to 5) is shaded "
            "or marked for 'Quality', 'Efficiency', and 'Timeliness'. \n"
            "Return ONLY a raw JSON object (no markdown formatting, no backticks). The keys must be exact: "
            "{\"ticket_id\": \"...\", \"quality\": X, \"efficiency\": X, \"timeliness\": X}"
        )

        # Gemini requires the image to be structured with mime_type and data
        image_parts = [
            {
                "mime_type": "image/jpeg",
                "data": image_bytes
            }
        ]

        # Initialize the model
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")

        # Generate content
        response = model.generate_content([prompt, image_parts[0]])

        # The response text should be the raw JSON
        response_text = response.text.strip()
        
        # Strip potential markdown formatting if the model disobeys instructions
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        response_text = response_text.strip()

        # Parse JSON
        extracted_data = json.loads(response_text)
        return extracted_data

    except json.JSONDecodeError as e:
        print(f"JSON Decode Error in Gemini response: {e}")
        print(f"Raw response: {response.text if 'response' in locals() else 'None'}")
        return None
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return None
