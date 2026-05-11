import json
import base64
import logging
import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger(__name__)
genai.configure(api_key=settings.GEMINI_API_KEY)

def analyze_jrf_image(image_data):
    try:
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}

        # Use the fast, multimodal model
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = (
            "You are a strict data extraction assistant. Analyze this scanned Job Request Form. "
            "1. Find the 'Ticket ID' text (usually starts with TKT-). "
            "2. Look at the Performance Indicator table. Tell me which number (1 to 5) is shaded "
            "or marked for 'Quality', 'Efficiency', and 'Timeliness'. Return ONLY a raw JSON object. "
            "The keys must be exact: {\"ticket_id\": \"...\", \"quality\": X, \"efficiency\": X, \"timeliness\": X}"
        )

        response = model.generate_content([prompt, image_part], generation_config={"response_mime_type": "application/json"})

        # DEBUG: log full response object for troubleshooting on live server
        logger.debug("Gemini raw response: %s", getattr(response, "__dict__", str(response)))

        # Try common ways to extract text safely
        raw_text = None
        if hasattr(response, "text") and response.text:
            raw_text = response.text.strip()
        elif hasattr(response, "output") and response.output:
            try:
                raw_text = response.output[0].content[0].text
            except Exception:
                raw_text = json.dumps(response.output)
        else:
            raw_text = str(response)

        # Remove any Markdown fences if Gemini adds them
        if isinstance(raw_text, str) and raw_text.startswith("```json") and raw_text.endswith("```"):
            raw_text = raw_text[len("```json"):-len("```")].strip()

        return json.loads(raw_text)
    except Exception as e:
        logger.error("Gemini OMR analysis error: %s", e)
        return {"error": str(e)}
